import { useEffect, useRef, type ReactNode } from "react";
import { AlertCircle, Inbox, X } from "lucide-react";
export function Status({
  loading,
  error,
  empty,
}: {
  loading?: boolean;
  error?: string;
  empty?: boolean;
}) {
  if (error)
    return (
      <div className="state error" role="alert">
        <AlertCircle size={22} />
        <div>
          <strong>数据读取失败</strong>
          <p>{error}</p>
          <button onClick={() => location.reload()}>重新加载</button>
        </div>
      </div>
    );
  if (loading)
    return (
      <div className="state" role="status">
        <div className="skeleton" />
        <p>正在读取数据库与证据…</p>
      </div>
    );
  if (empty)
    return (
      <div className="state" role="status">
        <Inbox size={28} />
        <p>当前场站、日期与数据模式没有可用记录。</p>
      </div>
    );
  return null;
}
export function Panel({
  title,
  subtitle,
  action,
  children,
  className = "",
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      <header className="panel-head">
        <div>
          <h2>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {action}
      </header>
      {children}
    </section>
  );
}
export function Drawer({
  title,
  children,
  onClose,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement;
    ref.current?.showModal();
    return () => {
      previous?.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className="drawer"
      aria-label={title}
      onCancel={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          const rect = e.currentTarget.getBoundingClientRect();
          if (
            e.clientX < rect.left ||
            e.clientY < rect.top ||
            e.clientX > rect.right ||
            e.clientY > rect.bottom
          )
            onClose();
        }
      }}
    >
      <div className="drawer-title">
        <h2>{title}</h2>
        <button onClick={onClose} aria-label="关闭抽屉">
          <X size={19} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
