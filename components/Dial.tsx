type Props = { size?: number; value?: number; dark?: boolean; label?: boolean };

/** Tick-mark score dial. 100 ticks; ticks below `value` are filled green. */
export default function Dial({ size = 216, value = 82, dark = false, label = true }: Props) {
  const r = size / 2;
  const ticks = Array.from({ length: 100 }, (_, i) => {
    const a = (i / 100) * Math.PI * 2 - Math.PI / 2;
    const major = i % 25 === 0;
    const outer = r - 2;
    const inner = outer - size * (major ? 0.075 : 0.05);
    return { i, major, x1: r + Math.cos(a) * inner, y1: r + Math.sin(a) * inner, x2: r + Math.cos(a) * outer, y2: r + Math.sin(a) * outer };
  });
  const on = dark ? "#4E9B72" : "#2F6B4A";
  const off = dark ? "#2A2F38" : "#DAD8D1";
  return (
    <div className="dial" style={{ width: size, height: size }} role="img" aria-label={`Verdict Score ${value} out of 100`}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        {ticks.map((t) => (
          <line key={t.i} x1={t.x1} y1={t.y1} x2={t.x2} y2={t.y2} strokeLinecap="round"
            stroke={t.i < value ? on : off} strokeWidth={t.major ? 2 : 1.4}
            className="tick" style={{ animationDelay: `${t.i * 9}ms` }} />
        ))}
      </svg>
      <div className="dial-c" style={{ color: dark ? "#fff" : undefined }}>
        <span className="serif" style={{ fontSize: size * 0.27 }}>{value}</span>
        {label && <span className="mono" style={{ fontSize: Math.max(10, size * 0.065) }}>/ 100</span>}
      </div>
    </div>
  );
}
