import { useEffect, useRef } from 'react';
import { METHODOLOGY_SECTIONS } from '../content/methodology';

export function MethodologyDialog({ version, onClose }: { version: string; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    const trigger = document.activeElement;
    element?.showModal();
    return () => {
      element?.close();
      if (trigger instanceof HTMLElement && trigger.isConnected) trigger.focus();
    };
  }, []);
  return (
    <dialog
      ref={dialog}
      className="methodology-dialog"
      aria-labelledby="methodology-title"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === dialog.current) onClose();
      }}
    >
      <div className="methodology-body">
        <div className="methodology-heading">
          <span className="eyebrow">МЕТОДИКА</span>
          <h2 id="methodology-title">Как считается оценка</h2>
          <button className="methodology-close" aria-label="Закрыть" onClick={onClose}>
            <svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16">
              <path
                d="M3 3l10 10M13 3 3 13"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>
        {METHODOLOGY_SECTIONS.map((section) => (
          <section key={section.title} className="methodology-section">
            <h3>{section.title}</h3>
            <ul>
              {section.items.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </section>
        ))}
        <p className="methodology-version">Версия данных {version || 'загружается'}</p>
        <button className="primary-button" onClick={onClose}>
          Понятно
        </button>
      </div>
    </dialog>
  );
}
