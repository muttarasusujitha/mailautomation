const UINT32_RANGE = 0x100000000

export function randomUnit() {
  const cryptoApi = globalThis.crypto
  if (!cryptoApi?.getRandomValues) return 0.5

  const values = new Uint32Array(1)
  cryptoApi.getRandomValues(values)
  return values[0] / UINT32_RANGE
}

export function randomBetween(min, max) {
  return min + randomUnit() * (max - min)
}

export function randomInt(maxExclusive) {
  return Math.floor(randomUnit() * maxExclusive)
}
