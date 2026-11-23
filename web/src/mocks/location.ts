const demoAddress = { lat: 55.7558, lon: 37.6176 };

export function hasDemoFinance(point: { lat: number; lon: number }): boolean {
  return point.lat === demoAddress.lat && point.lon === demoAddress.lon;
}
