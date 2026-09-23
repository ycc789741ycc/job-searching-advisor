/** "just now", "5 min ago", "3 hours ago", "6 days ago", then a date. Pure. */
export function ago(iso: string, now: Date = new Date()): string {
  const seconds = Math.max(0, (now.getTime() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return hours === 1 ? "an hour ago" : `${hours} hours ago`;
  const days = Math.floor(hours / 24);
  if (days < 14) return days === 1 ? "yesterday" : `${days} days ago`;
  return new Date(iso).toLocaleDateString();
}
