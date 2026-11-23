import { useEffect, useState } from "react";
import type { Scope } from "./types";
export function query(scope: Scope) {
  const p = new URLSearchParams();
  Object.entries(scope).forEach(([k, v]) => {
    if (v && k !== "selected_interval") p.set(k, v);
  });
  return p.toString();
}
export async function request<T>(
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const r = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers:
      body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  const data = await r.json();
  if (!r.ok)
    throw new Error(
      data.error ||
        (data.detail && JSON.stringify(data.detail)) ||
        data.answer_markdown ||
        `HTTP ${r.status}`,
    );
  return data as T;
}
export function useResource<T>(path: string | null, revision = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    if (!path) {
      setData(null);
      setError("");
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setData(null);
    request<T>(path, undefined, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setData(value);
      })
      .catch((e: Error) => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path, revision]);
  return { data, error, loading };
}
export function fmt(n: number | null | undefined, decimals = 2) {
  return n === null || n === undefined
    ? "—"
    : n.toLocaleString("zh-CN", {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      });
}
export function time(value: string) {
  return new Date(value).toLocaleTimeString("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}
export function stamp(value: string) {
  return new Date(value).toLocaleString("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour12: false,
  });
}
