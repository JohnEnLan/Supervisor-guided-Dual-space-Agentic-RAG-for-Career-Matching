const RGB_PATTERN = /^rgb\((\d+),\s*(\d+),\s*(\d+)\)$/;

function opaqueRgbChannels(color: string) {
  const match = color.match(RGB_PATTERN);
  if (!match) throw new Error(`Expected an opaque rgb() color, received ${color}`);
  return match.slice(1).map(Number);
}

function relativeLuminance(color: string) {
  return opaqueRgbChannels(color)
    .map((channel) => channel / 255)
    .map((channel) =>
      channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4,
    )
    .reduce(
      (total, channel, index) => total + channel * [0.2126, 0.7152, 0.0722][index],
      0,
    );
}

export function opaqueRgbContrastRatio(foreground: string, background: string) {
  const [lighter, darker] = [relativeLuminance(foreground), relativeLuminance(background)].sort(
    (left, right) => right - left,
  );
  return (lighter + 0.05) / (darker + 0.05);
}
