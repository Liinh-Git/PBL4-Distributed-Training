"""Real three-Node E2E in Linux network namespaces (WSL2 supported).

Run as root with the existing project dependencies. Each Agent and its child
Worker have their own network namespace/IP; control services share the host.
Persistent state is retained. No Docker, remote database or HF deployment needed.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import pwd
import shutil
import subprocess
import sys
from pathlib import Path

from e2e_agents import AgentHarness
from e2e_local import _parser


class NetworkHarness(AgentHarness):
    def __init__(self, args: argparse.Namespace):
        super().__init__(args)
        self.bridge = "pbl" + str(os.getpid())
        self.bridge_created = False
        self.namespaces: list[str] = []
        self.host_links: list[str] = []
        self.observed_workers = {}
        self.control_ip = args.control_ip
        self.bind_host = "0.0.0.0"
        self.advertised_host = self.control_ip
        self.agent_backend_url = f"http://{self.control_ip}:{self.backend_port}"
        self.dataset_manager_url = f"http://{self.control_ip}:{self.dataset_port}"
        self.result["case"] = "THREE-NETWORK-NAMESPACES"
        self.result["ports"]["dataset_manager_url"] = self.dataset_manager_url
        self.result["topology"] = {"control_ip": self.control_ip, "nodes": []}

    def ip(self, *args):
        subprocess.run(["ip", *args], check=True, capture_output=True, text=True)

    def setup_network(self):
        if self.reused_state and self.reused_state.get("control_ip") != self.control_ip:
            raise ValueError("Reused artifact origins require the original --control-ip")
        self.ip("link", "add", self.bridge, "type", "bridge")
        self.bridge_created = True
        self.ip("addr", "add", self.control_ip + "/24", "dev", self.bridge)
        self.ip("link", "set", self.bridge, "up")
        prefix = self.control_ip.rsplit(".", 1)[0]
        for index in range(3):
            ns = f"{self.bridge}-n{index}"
            host, peer = f"{self.bridge}h{index}", f"{self.bridge}p{index}"
            self.ip("netns", "add", ns)
            self.namespaces.append(ns)
            self.ip("link", "add", host, "type", "veth", "peer", "name", peer)
            self.host_links.append(host)
            self.ip("link", "set", peer, "netns", ns)
            self.ip("link", "set", host, "master", self.bridge)
            self.ip("link", "set", host, "up")
            address = f"{prefix}.{index + 11}"
            self.ip("-n", ns, "addr", "add", address + "/24", "dev", peer)
            self.ip("-n", ns, "link", "set", peer, "up")
            self.ip("-n", ns, "link", "set", "lo", "up")
            self.result["topology"]["nodes"].append({"namespace": ns, "ip": address})
        self.log(f"network ready bridge={self.bridge} control={self.control_ip}")

    def start_child(self, name, command, env=None):
        if name.startswith("agent-"):
            index = int(name.split("-")[1])
            command = ["ip", "netns", "exec", self.namespaces[index], *command]
        return super().start_child(name, command, env)

    def setup_postgres(self, env):
        bin_dir = Path(subprocess.check_output(["pg_config", "--bindir"], text=True).strip())
        pgdata = self.runtime_data / "postgres-data"
        account = pwd.getpwnam("postgres")
        if not self.args.reuse_runtime_data:
            pgdata.mkdir(mode=0o700)
            os.chown(pgdata, account.pw_uid, account.pw_gid)
            self.checked(
                "postgres-initdb",
                [
                    "runuser",
                    "-u",
                    "postgres",
                    "--",
                    str(bin_dir / "initdb"),
                    "-D",
                    str(pgdata),
                    "-U",
                    "postgres",
                    "--auth=trust",
                    "--encoding=UTF8",
                    "--no-locale",
                ],
            )
        self.start_child(
            "postgres",
            [
                "runuser",
                "-u",
                "postgres",
                "--",
                str(bin_dir / "postgres"),
                "-D",
                str(pgdata),
                "-h",
                "127.0.0.1",
                "-p",
                str(self.postgres_port),
            ],
            env,
        )
        self.wait_value(
            lambda: (
                subprocess.run(
                    [str(bin_dir / "pg_isready"), "-h", "127.0.0.1", "-p", str(self.postgres_port)],
                    capture_output=True,
                ).returncode
            ),
            lambda code: code == 0,
            30,
            "private PostgreSQL",
        )
        if not self.args.reuse_runtime_data:
            self.checked(
                "postgres-createdb",
                [
                    str(bin_dir / "createdb"),
                    "-h",
                    "127.0.0.1",
                    "-p",
                    str(self.postgres_port),
                    "-U",
                    "postgres",
                    "pbl4_e2e",
                ],
                env=env,
            )
        self.database_url = f"postgresql://postgres@127.0.0.1:{self.postgres_port}/pbl4_e2e"
        self.result["postgres_mode"] = "isolated local Linux PostgreSQL"

    def verify_cache_evidence(self, records):
        super().verify_cache_evidence(records)
        agents = [c for c in self.children if c.name.startswith("agent-")]
        netns_ids = []
        for index, agent_dir in enumerate(self.agent_dirs):
            allocations = json.loads((agent_dir / "allocations.json").read_text())
            record = next(r for r in records if r["allocation_id"] in allocations)
            agent_ns = os.readlink(f"/proc/{agents[index].process.pid}/ns/net")
            if self.observed_workers.get(record["allocation_id"]) != agent_ns:
                raise AssertionError("Live Worker namespace inheritance was not observed")
            netns_ids.append(agent_ns)
            worker = next(
                w for w in self.result["workers"] if w["allocation_id"] == record["allocation_id"]
            )
            self.result["topology"]["nodes"][index].update(
                {
                    "netns_inode": agent_ns,
                    "agent_pid": agents[index].process.pid,
                    "worker_pid": record["pid"],
                    "node_id": worker["node_id"],
                    "allocation_id": record["allocation_id"],
                }
            )
        if len(set(netns_ids)) != 3:
            raise AssertionError("Agents share a network namespace")
        state_path = self.runtime_data / "smoke-state.json"
        state = json.loads(state_path.read_text())
        state["control_ip"] = self.control_ip
        state_path.write_text(json.dumps(state, indent=2))

    def _poll_attempt(self, attempt_id):
        result = super()._poll_attempt(attempt_id)
        for directory in self.agent_dirs:
            path = directory / "allocations.json"
            if path.is_file():
                for record in json.loads(path.read_text()).values():
                    if record["attempt_id"] == attempt_id and record.get("pid"):
                        with contextlib.suppress(FileNotFoundError):
                            self.observed_workers[record["allocation_id"]] = os.readlink(
                                f"/proc/{record['pid']}/ns/net"
                            )
        return result

    def finish(self, error):
        network_errors = []
        try:
            super().finish(error)
        finally:
            for namespace in reversed(self.namespaces):
                remaining = subprocess.check_output(
                    ["ip", "netns", "pids", namespace], text=True
                ).strip()
                if remaining:
                    network_errors.append(f"Orphan PIDs in {namespace}: {remaining}")
                try:
                    self.ip("netns", "del", namespace)
                except subprocess.CalledProcessError as exc:
                    network_errors.append(str(exc))
            for host in self.host_links:
                subprocess.run(["ip", "link", "del", host], capture_output=True)
            if self.bridge_created:
                subprocess.run(["ip", "link", "del", self.bridge], capture_output=True)
                if (
                    subprocess.run(
                        ["ip", "link", "show", self.bridge], capture_output=True
                    ).returncode
                    == 0
                ):
                    network_errors.append("Owned bridge survived cleanup")
            self.result["network_cleanup"] = network_errors or "PASS"
            if network_errors:
                self.result["verdict"] = "FAIL"
            (self.artifacts / "result.json").write_text(
                json.dumps(self.result, indent=2, default=str)
            )
        if network_errors:
            raise RuntimeError(str(network_errors))


def main():
    if sys.platform != "linux" or os.geteuid() != 0:
        raise SystemExit("Run under Linux/WSL2 as root to create isolated network namespaces")
    for command in ["ip", "pg_config", "runuser"]:
        if not shutil.which(command):
            raise SystemExit(f"Required command unavailable: {command}")
    repo = Path(__file__).resolve().parents[1]
    os.environ.update(
        {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "safe.directory",
            "GIT_CONFIG_VALUE_0": str(repo),
        }
    )
    parser = _parser()
    parser.description = __doc__
    parser.add_argument("--dataset-manager-repo", required=True)
    parser.add_argument("--state-root", default="/var/tmp/pbl4-network-e2e")
    parser.add_argument("--control-ip", default="10.203.42.1")
    parser.add_argument(
        "--model-id", default="small_cnn", choices=["small_cnn", "resnet18_groupnorm"]
    )
    parser.add_argument("--workload-policy", default="equal", choices=["equal", "dbs"])
    parser.add_argument("--work-units-per-step", type=int, default=3)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--agents-before-backend", action="store_true")
    parser.add_argument(
        "--scenario", choices=["happy", "cache-reuse", "cache-repair"], default="happy"
    )
    parser.add_argument("--hold-seconds", type=int, default=0)
    parser.set_defaults(
        batch_size=16,
        poll_interval=0.25,
        heartbeat_timeout=15,
        training_timeout=120,
        storage_backend="local",
    )
    args = parser.parse_args()
    os.environ.update(
        {
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_1": "safe.directory",
            "GIT_CONFIG_VALUE_1": str(Path(args.dataset_manager_repo).resolve()),
        }
    )
    if args.database_url or args.dataset_manager_url or not args.preserve_runtime_data:
        parser.error(
            "Use this harness's private database/artifact server and preserve persistent state"
        )
    Path(args.state_root).mkdir(parents=True, exist_ok=True)
    harness = NetworkHarness(args)
    error = None
    try:
        harness.setup_network()
        harness.run()
    except BaseException as exc:
        error = exc
        harness.log(f"FAIL {type(exc).__name__}: {exc}")
    finally:
        harness.finish(error)
    if error:
        raise error
    harness.log(f"PASS network cleanup={harness.result['network_cleanup']}")


if __name__ == "__main__":
    main()
