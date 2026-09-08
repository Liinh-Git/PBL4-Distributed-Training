"""Private StrictBSP set barrier. Access is serialized by the policy lock."""


class Barrier:
    def __init__(self, membership: frozenset[int]) -> None:
        if not membership:
            raise ValueError("Empty membership")
        self._membership = frozenset(membership)
        self._arrived: set[int] = set()

    def arrive(self, worker_id: int) -> bool:
        if worker_id not in self._membership:
            raise ValueError("Foreign member")
        if worker_id in self._arrived:
            return False
        self._arrived.add(worker_id)
        return True

    @property
    def complete(self) -> bool:
        return self._arrived == self._membership

    @property
    def arrived(self) -> frozenset[int]:
        return frozenset(self._arrived)
