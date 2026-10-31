import { useEffect, useRef } from 'react';

export function WelcomeToast({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);
  return (
    <dialog
      ref={dialog}
      className="welcome-dialog"
      aria-labelledby="welcome-title"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === dialog.current) onClose();
      }}
    >
      <div className="welcome-body">
        <span className="eyebrow">ДОБРО ПОЖАЛОВАТЬ</span>
        <h2 id="welcome-title">Проверьте место до договора аренды</h2>
        <ol>
          <li>Выберите город и вид бизнеса</li>
          <li>Найдите адрес или нажмите на участок карты</li>
          <li>Получите выручку, расходы и срок окупаемости</li>
        </ol>
        <div className="welcome-actions">
          <a className="primary-button button-link" href="#map" onClick={onClose}>
            Открыть карту
          </a>
          <button onClick={onClose}>Сначала прочитать о сервисе</button>
        </div>
      </div>
    </dialog>
  );
}
