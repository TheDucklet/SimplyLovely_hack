import { HERO_VIEWBOX, LANDING_EXAMPLE, LANDING_FACTS, LANDING_STEPS, heroHexes } from '../landing';

const HEXES = heroHexes();

export function Landing({ onCreditMode }: { onCreditMode: () => void }) {
  return (
    <div className="landing">
      <section className="hero" aria-labelledby="hero-title">
        <div className="hero-copy">
          <p className="eyebrow">КОФЕЙНИ И ПУНКТЫ ВЫДАЧИ · МОСКВА И ТУЛА</p>
          <h1 id="hero-title">Узнайте, окупится ли точка, до договора аренды</h1>
          <p className="hero-lead">
            Выберите адрес на карте и за минуту получите выручку в диапазоне p10-p90, расходы на
            аренду, зарплаты и налоги и срок окупаемости с источником каждого допущения.
          </p>
          <div className="hero-actions">
            <a className="primary-button button-link button-large" href="#map">
              Проверить адрес
            </a>
            <a className="button-link button-large" href="#how">
              Как это работает
            </a>
          </div>
        </div>
        <div className="hero-visual">
          <svg className="hero-hexes" viewBox={HERO_VIEWBOX} aria-hidden="true">
            {HEXES.map((hex) => (
              <polygon key={hex.points} points={hex.points} fill={hex.fill} />
            ))}
          </svg>
          <div className="hero-card">
            <span className="hero-card-place">
              {LANDING_EXAMPLE.address} · {LANDING_EXAMPLE.niche}
            </span>
            <strong className="hero-card-value">{LANDING_EXAMPLE.revenue}</strong>
            <span className="hero-card-note">выручка в месяц, медиана</span>
            <dl>
              <div>
                <dt>Прибыль</dt>
                <dd className="positive">{LANDING_EXAMPLE.profit}</dd>
              </div>
              <div>
                <dt>Окупаемость</dt>
                <dd>{LANDING_EXAMPLE.payback}</dd>
              </div>
            </dl>
          </div>
        </div>
      </section>
      <section id="proof" className="facts" aria-label="Цифры модели">
        <div className="facts-grid">
          {LANDING_FACTS.map((fact) => (
            <div key={fact.label} className="fact">
              <strong>{fact.value}</strong>
              <span>{fact.label}</span>
            </div>
          ))}
        </div>
      </section>
      <section id="how" className="steps" aria-labelledby="steps-title">
        <h2 id="steps-title">Три шага до ответа</h2>
        <ol className="steps-grid">
          {LANDING_STEPS.map((step, index) => (
            <li key={step.title} className="step">
              <span className="step-number" aria-hidden="true">
                {index + 1}
              </span>
              <h3>{step.title}</h3>
              <p>{step.text}</p>
            </li>
          ))}
        </ol>
      </section>
      <section id="bank" className="bank-band" aria-labelledby="bank-band-title">
        <div className="bank-band-inner">
          <div>
            <p className="eyebrow">ДЛЯ КРЕДИТНОГО СПЕЦИАЛИСТА</p>
            <h2 id="bank-band-title">Сверьте бизнес-план клиента с рынком за минуту</h2>
            <p>
              Введите выручку из плана, и сервис покажет, попадает ли она в расчётный диапазон для
              этого адреса.
            </p>
          </div>
          <a className="button-link button-large button-inverse" href="#map" onClick={onCreditMode}>
            Включить режим специалиста
          </a>
        </div>
      </section>
    </div>
  );
}
