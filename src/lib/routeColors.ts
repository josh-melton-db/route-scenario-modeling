const ROUTE_COLORS: [number, number, number][] = [
  [34, 211, 238],
  [244, 114, 182],
  [251, 191, 36],
  [129, 140, 248],
  [74, 222, 128],
  [248, 113, 113],
  [167, 139, 250],
  [250, 204, 21],
]

export function routeColor(index: number): [number, number, number] {
  return ROUTE_COLORS[index % ROUTE_COLORS.length]
}

export function routeColorCss(index: number): string {
  const [r, g, b] = routeColor(index)
  return `rgb(${r}, ${g}, ${b})`
}
