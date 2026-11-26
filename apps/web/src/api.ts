import { useEffect, useState } from "react";
import type { Scope } from "./types";
import { businessText } from "./presentation";
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
      businessText(data.error || (typeof data.detail==="string"?data.detail:data.detail?"输入内容不符合要求，请检查填写项。":null) || data.answer_markdown || "请求未完成，请稍后重试。"),
    );
  return data as T;
}
export function useResource<T>(
  path: string | null,
  revision: number | string = 0,
  refreshMs = 0,
) {
  const [state, setState] = useState<{
    path: string | null;
    data: T | null;
    error: string;
    checking: boolean;
    checkedAt: string | null;
  }>({ path: null, data: null, error: "", checking: false, checkedAt: null });
  useEffect(() => {
    if (!path) {
      return;
    }
    let controller: AbortController | null = null;
    let stopped = false;
    async function check() {
      controller?.abort();
      const current = new AbortController();
      controller = current;
      setState((s) => ({
        path,
        data: s.path === path ? s.data : null,
        error: "",
        checking: true,
        checkedAt: s.path === path ? s.checkedAt : null,
      }));
      try {
        const data = await request<T>(path!, undefined, current.signal);
        if (!stopped && !current.signal.aborted)
          setState({
            path,
            data,
            error: "",
            checking: false,
            checkedAt: new Date().toISOString(),
          });
      } catch (e) {
        if (!stopped && !current.signal.aborted)
          setState((s) => ({
            ...s,
            error: (e as Error).message,
            checking: false,
          }));
      }
    }
    void check();
    const timer =
      refreshMs > 0
        ? window.setInterval(() => {
            if (document.visibilityState === "visible") void check();
          }, refreshMs)
        : null;
    const visible = () => {
      if (refreshMs > 0 && document.visibilityState === "visible") void check();
    };
    document.addEventListener("visibilitychange", visible);
    return () => {
      stopped = true;
      controller?.abort();
      if (timer !== null) window.clearInterval(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [path, revision, refreshMs]);
  const same = !!path && state.path === path;
  const data = same ? state.data : null;
  return {
    data,
    error: same ? state.error : "",
    loading: !!path && (!same || (!data && state.checking)),
    refreshing: same && state.checking,
    checkedAt: same ? state.checkedAt : null,
  };
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
