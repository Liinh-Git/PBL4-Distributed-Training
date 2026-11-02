export function formatDateTime(isoString?: string | null): string {
  if (!isoString) return '—';
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return String(isoString);
    const day = String(d.getDate()).padStart(2, '0');
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const year = d.getFullYear();
    const hours = String(d.getHours()).padStart(2, '0');
    const mins = String(d.getMinutes()).padStart(2, '0');
    const secs = String(d.getSeconds()).padStart(2, '0');
    return `${day}/${month}/${year} ${hours}:${mins}:${secs}`;
  } catch {
    return String(isoString);
  }
}

export function formatDateOnly(isoString?: string | null): string {
  if (!isoString) return '—';
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return String(isoString);
    const day = String(d.getDate()).padStart(2, '0');
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const year = d.getFullYear();
    return `${day}/${month}/${year}`;
  } catch {
    return String(isoString);
  }
}

export function formatStrategy(strategy?: string | null): string {
  if (!strategy) return 'Đồng bộ chặt';
  const s = strategy.toLowerCase();
  if (s.includes('bsp') || s.includes('strict')) return 'Đồng bộ chặt';
  if (s === 'dbs') return 'Lập lịch thích ứng (DBS)';
  return 'Đồng bộ chặt';
}
