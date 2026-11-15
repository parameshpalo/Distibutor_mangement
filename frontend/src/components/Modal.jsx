import { useEffect } from "react";

/** A dialog over the current page. Escape closes it, as people expect. */
export default function Modal({ title, subtitle, onClose, children, footer }) {
  useEffect(() => {
    const onKey = (event) => event.key === "Escape" && onClose?.();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => event.target === event.currentTarget && onClose?.()}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head">
          <div>
            <div className="modal-title">{title}</div>
            {subtitle ? (
              <div className="sub" style={{ marginTop: 2 }}>
                {subtitle}
              </div>
            ) : null}
          </div>
          <button className="ghost" onClick={onClose} title="Close">
            ✕
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer ? <div className="modal-foot">{footer}</div> : null}
      </div>
    </div>
  );
}

/** A labelled input bound to one key of a form-state object. */
export function Field({
  label,
  value,
  onChange,
  type = "text",
  hint,
  options,
  span,
  ...rest
}) {
  const className = span ? "field span-all" : "field";
  return (
    <label className={className}>
      <span>{label}</span>
      {options ? (
        <select value={value ?? ""} onChange={(e) => onChange(e.target.value)} {...rest}>
          {options.map(([key, text]) => (
            <option key={key} value={key}>
              {text}
            </option>
          ))}
        </select>
      ) : (
        <input
          type={type}
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value)}
          {...rest}
        />
      )}
      {hint ? <div className="form-hint">{hint}</div> : null}
    </label>
  );
}

/** A choice of two or three, shown as one control rather than a dropdown. */
export function Segmented({ label, value, onChange, options, hint }) {
  return (
    <label className="field">
      <span>{label}</span>
      <div className="segmented">
        {options.map(([key, text]) => (
          <button
            key={key}
            type="button"
            className={value === key ? "primary" : ""}
            onClick={() => onChange(key)}
          >
            {text}
          </button>
        ))}
      </div>
      {hint ? <div className="form-hint">{hint}</div> : null}
    </label>
  );
}
