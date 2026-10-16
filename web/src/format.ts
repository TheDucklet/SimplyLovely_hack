const numberFormatter = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 });
const decimalFormatter = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 3 });

export function decimal(value: number): string {
  return decimalFormatter.format(value).replace(/\u00a0|\u202f/g, ' ');
}

export function number(value: number): string {
  return numberFormatter.format(value).replace(/\u00a0|\u202f/g, ' ');
}

export function rubles(value: number): string {
  return `${number(value)} ₽`;
}

export function months(value: number | null): string {
  return value === null ? 'Не окупается' : `${decimal(Math.round(value * 10) / 10)} мес.`;
}

export function message(error: unknown): string {
  return error instanceof Error ? error.message : 'Не удалось загрузить данные';
}
