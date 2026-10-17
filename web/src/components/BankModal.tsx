import { useEffect, useRef } from 'react';
export function BankModal({ action, onClose }: { action: string; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);
  return (
    <dialog
      ref={dialog}
      className="bank-dialog"
      aria-labelledby="bank-title"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === dialog.current) onClose();
      }}
    >
      <div className="bank-dialog-body">
        <span className="eyebrow">ВТБ БИЗНЕС · ПИЛОТ</span>
        <h2 id="bank-title">{action}</h2>
        <p>В пилоте здесь будет переход в ВТБ Бизнес</p>
        <button className="primary-button" autoFocus onClick={onClose}>
          Понятно
        </button>
      </div>
    </dialog>
  );
}
