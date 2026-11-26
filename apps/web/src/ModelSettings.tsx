import { businessText, analysisLabel } from "./presentation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  ArrowLeft,
  Check,
  Eye,
  EyeOff,
  KeyRound,
  LoaderCircle,
  PlugZap,
  Save,
  Settings2,
} from "lucide-react";
import RuntimeSettings from "./RuntimeSettings";

type Config = {
  enabled: boolean;
  base_url: string;
  model: string;
  api_key_configured: boolean;
  api_key_hint: string;
  timeout_seconds: number;
  max_output_tokens: number;
  ready: boolean;
  updated_at: string | null;
  llm_mode: string;
};
type Connection = {
  status: string;
  model: string;
  latency_ms: number;
  evidence_contract_passed: boolean;
};

async function call<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    cache: "no-store",
    headers:
      body === undefined
        ? undefined
        : { "Content-Type": "application/json", "X-CECEP-Settings": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const value = await response.json();
  if (!response.ok)
    throw new Error(
      businessText(
        value.error ||
          (typeof value.detail === "string"
            ? value.detail
            : "连接未完成，请检查服务设置后重试。"),
      ),
    );
  return value;
}

export default function ModelSettings() {
  const [saved, setSaved] = useState<Config | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("qwen3.8-27b");
  const [apiKey, setApiKey] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [showKey, setShowKey] = useState(false);
  const [timeout, setTimeoutValue] = useState(30);
  const [tokens, setTokens] = useState(1024);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"save" | "test" | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [connection, setConnection] = useState<Connection | null>(null);
  const keyInput = useRef<HTMLInputElement>(null);
  const dirty = Boolean(
    saved &&
    (enabled !== saved.enabled ||
      baseUrl !== saved.base_url ||
      model !== saved.model ||
      apiKey ||
      clearKey ||
      timeout !== saved.timeout_seconds ||
      tokens !== saved.max_output_tokens),
  );
  function apply(config: Config) {
    setSaved(config);
    setEnabled(config.enabled);
    setBaseUrl(config.base_url);
    setModel(config.model);
    setTimeoutValue(config.timeout_seconds);
    setTokens(config.max_output_tokens);
    setApiKey("");
    setClearKey(false);
    setShowKey(false);
    if (keyInput.current) keyInput.current.value = "";
  }
  useEffect(() => {
    let active = true;
    call<Config>("/api/v1/settings/llm")
      .then((config) => {
        if (active) apply(config);
      })
      .catch((e) => {
        if (active) setError((e as Error).message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy("save");
    setError("");
    setMessage("");
    setConnection(null);
    try {
      const result = await call<Config>("/api/v1/settings/llm", {
        enabled,
        base_url: baseUrl.trim(),
        model: model.trim(),
        timeout_seconds: timeout,
        max_output_tokens: tokens,
        ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
        clear_api_key: clearKey,
      });
      apply(result);
      setMessage(
        "配置已保存，后续 Agent 请求立即使用新配置。连接状态请单独测试。",
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }
  async function test() {
    setBusy("test");
    setError("");
    setMessage("");
    setConnection(null);
    try {
      setConnection(await call<Connection>("/api/v1/settings/llm/test", {}));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }
  return (
    <main className="model-settings-page">
      <a className="button" href="/">
        <ArrowLeft size={15} />
        返回工作台
      </a>
      <header className="model-settings-heading">
        <div>
          <h1>
            <Settings2 size={23} />
            Agent 模型配置
          </h1>
          <p>
            配置项目的外部语言模型。功率、电价与收益仍由业务模型和确定性工具计算。
          </p>
        </div>
        {saved && (
          <span className={`badge ${saved.ready ? "success" : "warning"}`}>
            {saved.ready ? "已配置 · 连接待验证" : "确定性工具模式"}
          </span>
        )}
      </header>
      {loading ? (
        <section className="panel model-settings-loading" role="status">
          <LoaderCircle size={22} />
          正在读取配置…
        </section>
      ) : !saved ? (
        <section className="panel model-settings-loading" role="alert">
          <p>{error || "配置读取失败"}</p>
          <button onClick={() => location.reload()}>重新加载</button>
        </section>
      ) : (
        <div className="model-settings-layout">
          <section className="panel model-settings-form">
            <h2>连接与模型</h2>
            <p className="muted">
              Qwen3.8 27B 为默认选项。服务模型名称
              和区域地址需与服务商控制台一致。
            </p>
            <form onSubmit={save} autoComplete="off">
              <fieldset disabled={busy !== null}>
                <label className="model-settings-toggle">
                  <input
                    type="checkbox"
                    checked={enabled}
                    onChange={(e) => setEnabled(e.target.checked)}
                  />
                  <span>
                    <strong>启用外部模型</strong>
                    <small>
                      关闭后使用 规则工具分析，业务计算仍可正常使用。
                    </small>
                  </span>
                </label>
                <label className="model-settings-field">
                  服务地址
                  <input
                    type="url"
                    value={baseUrl}
                    onChange={(e) => setBaseUrl(e.target.value)}
                    placeholder="填写服务商提供的 HTTPS API 根地址"
                    required={enabled}
                    maxLength={2000}
                  />
                  <small>
                    填写 API 根地址，不包含
                    /chat/completions。地址未确认时可先停用并保存密钥。
                  </small>
                </label>
                <label className="model-settings-field">
                  服务模型名称
                  <input
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                    maxLength={200}
                    required
                    spellCheck={false}
                  />
                  <small>
                    默认 qwen3.8-27b；若控制台使用其他模型名称，请填写完整名称。
                  </small>
                </label>
                <label className="model-settings-field" htmlFor="model-api-key">
                  访问密钥
                  <span className="model-key-control">
                    <input
                      ref={keyInput}
                      id="model-api-key"
                      type={showKey ? "text" : "password"}
                      autoComplete="new-password"
                      value={apiKey}
                      onChange={(e) => {
                        setApiKey(e.target.value);
                        setClearKey(false);
                      }}
                      disabled={clearKey}
                      placeholder={
                        saved.api_key_configured
                          ? "已保存；留空保留现有密钥"
                          : "输入新的 访问密钥"
                      }
                      maxLength={4096}
                      spellCheck={false}
                    />
                    <button
                      type="button"
                      onClick={() => setShowKey((v) => !v)}
                      aria-label={
                        showKey ? "隐藏新输入的密钥" : "显示新输入的密钥"
                      }
                      aria-pressed={showKey}
                    >
                      {showKey ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </span>
                  <small>
                    <KeyRound size={12} /> {saved.api_key_hint}
                    。保存后清空输入框，服务器不会返回完整密钥。
                  </small>
                </label>
                {saved.api_key_configured && (
                  <label className="model-settings-clear">
                    <input
                      type="checkbox"
                      checked={clearKey}
                      onChange={(e) => {
                        setClearKey(e.target.checked);
                        if (e.target.checked) {
                          setApiKey("");
                          setEnabled(false);
                        }
                      }}
                    />
                    保存时移除已存密钥，并停用外部模型
                  </label>
                )}
                <section className="model-settings-advanced">
                  <h3>服务响应设置</h3>
                  <div className="model-settings-parameters">
                    <label className="model-settings-field">
                      超时（秒）
                      <input
                        type="number"
                        min={5}
                        max={120}
                        value={timeout}
                        onChange={(e) =>
                          setTimeoutValue(Number(e.target.value))
                        }
                        required
                      />
                    </label>
                    <label className="model-settings-field">
                      回复长度预算
                      <input
                        type="number"
                        min={128}
                        max={4096}
                        value={tokens}
                        onChange={(e) => setTokens(Number(e.target.value))}
                        required
                      />
                    </label>
                  </div>
                  <p className="muted">
                    回复基于已有业务证据生成，数值由业务计算提供。
                  </p>
                </section>
                <div className="model-settings-actions">
                  <button
                    className="primary-button"
                    type="submit"
                    disabled={!dirty}
                  >
                    <Save size={15} />
                    {busy === "save" ? "保存中…" : "保存配置"}
                  </button>
                  <button
                    type="button"
                    onClick={() => void test()}
                    disabled={dirty || !saved.ready}
                  >
                    <PlugZap size={15} />
                    {busy === "test" ? "正在测试…" : "测试已保存的连接"}
                  </button>
                  <span className="muted">
                    {dirty ? "有未保存修改，请先保存" : "配置已与服务器同步"}
                  </span>
                </div>
              </fieldset>
            </form>
            {error && (
              <div className="inline-error" role="alert">
                {businessText(error)}
              </div>
            )}
            {message && (
              <div className="notice model-settings-result" role="status">
                <Check size={16} />
                <p>{businessText(message)}</p>
              </div>
            )}
            {connection && !dirty && (
              <div className="notice model-settings-result" role="status">
                <Check size={16} />
                <p>
                  真实连接成功 · {connection.model} · {connection.latency_ms} ms
                  <br />
                  证据选择协议：
                  {connection.evidence_contract_passed ? "通过" : "未通过"}
                  。本测试不验证业务预测效果。
                </p>
              </div>
            )}
          </section>
          <aside className="panel model-settings-summary">
            <h2>生效范围</h2>
            <dl>
              <dt>当前模式</dt>
              <dd>{analysisLabel(saved.llm_mode)}</dd>
              <dt>已保存模型</dt>
              <dd>{saved.model}</dd>
              <dt>密钥状态</dt>
              <dd>{saved.api_key_hint}</dd>
              <dt>最近保存</dt>
              <dd>
                {saved.updated_at
                  ? new Date(saved.updated_at).toLocaleString("zh-CN", {
                      timeZone: "Asia/Shanghai",
                    })
                  : "尚未通过页面保存"}
              </dd>
            </dl>
            <h3>Agent 的工作方式</h3>
            <p>
              先查询数据库、计算指标和检索知识，再由语言模型选择既有证据。数值不交给语言模型自由生成。
            </p>
            <p>
              服务不可达、模型无权限或输出不符合协议时会显示失败，并保留工具证据，不会显示虚假的连接成功。
            </p>
            <p className="muted">
              保存设置无需重启服务，不下载模型权重，也不会启动训练。
            </p>
          </aside>
        </div>
      )}
      <RuntimeSettings />
    </main>
  );
}
