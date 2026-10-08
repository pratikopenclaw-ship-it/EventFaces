import type { SVGProps } from "react";

// Icons for the selfie capture guide (pre-flight checklist + per-step head pose). Same
// plain inline SVG approach as empty-icons.tsx: no icon library, 24x24, stroke = currentColor.

type IconProps = SVGProps<SVGSVGElement>;

const base = {
  viewBox: "0 0 24 24",
  fill: "none" as const,
  stroke: "currentColor",
  strokeWidth: 1.5,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export function SunIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <circle cx="12" cy="12" r="4.5" />
      <path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M5.6 18.4l1.8-1.8M16.6 7.4l1.8-1.8" />
    </svg>
  );
}

export function FaceIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M9 10.5h.01M15 10.5h.01" />
      <path d="M8.5 14c.9 1 2.1 1.5 3.5 1.5s2.6-.5 3.5-1.5" />
    </svg>
  );
}

export function NoGlassesIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <circle cx="7" cy="13" r="3" />
      <circle cx="17" cy="13" r="3" />
      <path d="M10 13h4M4 12l-1.5-.5M20 12l1.5-.5" />
      <path d="M4 4l16 16" />
    </svg>
  );
}

export function SinglePersonIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <circle cx="12" cy="8" r="3.5" />
      <path d="M5 20c0-3.6 3.1-6 7-6s7 2.4 7 6" />
    </svg>
  );
}

export function FocusIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <circle cx="12" cy="12" r="2" />
      <path d="M3 8V5a2 2 0 0 1 2-2h3M21 8V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3M21 16v3a2 2 0 0 1-2 2h-3" />
    </svg>
  );
}

/** A head outline with the nose shown where it should point: left / center / right. */
export function HeadPoseIcon({ direction, ...props }: IconProps & { direction: "front" | "left" | "right" }) {
  const noseX = direction === "left" ? 9.5 : direction === "right" ? 14.5 : 12;
  return (
    <svg {...base} {...props}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M9.5 10h.01M14.5 10h.01" />
      <circle cx={noseX} cy="13.3" r="1.1" fill="currentColor" stroke="none" />
    </svg>
  );
}
