/** Share reads between subscribers; cancellation belongs to each subscriber. */
export class SharedReads {
  private pending = new Map<string, {
    promise: Promise<unknown>; controller: AbortController; subscribers: number;
    abortTimer?: ReturnType<typeof setTimeout>;
  }>();
  private cache = new Map<string, { value: unknown; expires: number }>();

  constructor(private readonly capacity = 32) {}

  invalidate(key: string) { this.cache.delete(key); }

  read<T>(
    key: string, load: (signal: AbortSignal) => Promise<T>, signal?: AbortSignal,
    cacheMs: number | ((value: T) => number) = 0,
  ): Promise<T> {
    if (signal?.aborted) return Promise.reject(signal.reason ?? new DOMException('Aborted', 'AbortError'));
    const cached = this.cache.get(key);
    if (cached && cached.expires > Date.now()) {
      this.cache.delete(key);
      this.cache.set(key, cached);
      return Promise.resolve(cached.value as T);
    }
    this.cache.delete(key);
    let entry = this.pending.get(key);
    if (!entry) {
      const controller = new AbortController();
      entry = { controller, subscribers: 0, promise: Promise.resolve().then(() => load(controller.signal)) };
      const created = entry;
      entry.promise = entry.promise.then(value => {
        const ttl = typeof cacheMs === 'function' ? cacheMs(value as T) : cacheMs;
        if (ttl > 0 && !controller.signal.aborted) {
          for (const [k, item] of this.cache) if (item.expires <= Date.now()) this.cache.delete(k);
          this.cache.delete(key);
          this.cache.set(key, { value, expires: Date.now() + ttl });
          while (this.cache.size > this.capacity) this.cache.delete(this.cache.keys().next().value!);
        }
        return value;
      }).finally(() => {
        if (created.abortTimer) clearTimeout(created.abortTimer);
        if (this.pending.get(key) === created) this.pending.delete(key);
      });
      this.pending.set(key, entry);
    }
    const current = entry;
    if (current.abortTimer) clearTimeout(current.abortTimer);
    current.subscribers++;
    return new Promise<T>((resolve, reject) => {
      let done = false;
      const release = () => {
        if (done) return false;
        done = true;
        signal?.removeEventListener('abort', abort);
        if (--current.subscribers === 0 && this.pending.get(key) === current) {
          // Allow React StrictMode's synchronous cleanup/remount to reuse this read.
          current.abortTimer = setTimeout(() => {
            if (current.subscribers === 0 && this.pending.get(key) === current) {
              this.pending.delete(key);
              current.controller.abort();
            }
          }, 0);
        }
        return true;
      };
      const abort = () => {
        if (release()) reject(signal?.reason ?? new DOMException('Aborted', 'AbortError'));
      };
      signal?.addEventListener('abort', abort, { once: true });
      current.promise.then(value => { if (release()) resolve(value as T); }, error => { if (release()) reject(error); });
    });
  }
}
