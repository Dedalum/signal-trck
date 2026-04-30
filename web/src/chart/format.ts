/** Price + time formatters for Lightweight Charts axes / tooltips. */

export function formatPrice(price: number): string {
  if (price >= 1000) return price.toFixed(0);
  if (price >= 10) return price.toFixed(2);
  if (price >= 1) return price.toFixed(3);
  return price.toFixed(6);
}

export function unixToBusinessDay(ts_utc: number): number {
  // Lightweight Charts accepts both UTCTimestamp and BusinessDay strings;
  // we use UTCTimestamp (seconds-since-epoch) directly. This helper exists
  // so the type ergonomics stay obvious at call sites.
  return ts_utc;
}
