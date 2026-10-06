import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

function IconBase({ children, ...props }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  );
}

export function ShareIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <circle cx="18" cy="5" r="2.4" />
      <circle cx="6" cy="12" r="2.4" />
      <circle cx="18" cy="19" r="2.4" />
      <path d="m8.2 10.9 7.6-4.5M8.2 13.1l7.6 4.5" />
    </IconBase>
  );
}

export function MaterialsIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M6 3h8l4 4v14H6z" />
      <path d="M14 3v5h4M9 12h6M9 16h6" />
    </IconBase>
  );
}

export function BookIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M12 6c-2.3-1.5-5-1.8-8-1.5v14c3-.3 5.7 0 8 1.5 2.3-1.5 5-1.8 8-1.5v-14c-3-.3-5.7 0-8 1.5Z" />
      <path d="M12 6v14" />
    </IconBase>
  );
}

export function VideoIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <rect x="3" y="5" width="18" height="14" rx="2.5" />
      <path d="m10 9 5 3-5 3V9Z" fill="currentColor" stroke="none" />
    </IconBase>
  );
}

export function ChatIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M20 11.5a7.5 7.5 0 0 1-8 7.5 8.7 8.7 0 0 1-3.6-.8L4 20l1.5-4A7.5 7.5 0 1 1 20 11.5Z" />
    </IconBase>
  );
}

export function StudioIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M9 3h6M10 3v5l-5.4 9.2A2.5 2.5 0 0 0 6.8 21h10.4a2.5 2.5 0 0 0 2.2-3.8L14 8V3" />
      <path d="M7.4 16h9.2" />
    </IconBase>
  );
}

export function CardsIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <rect x="7" y="4" width="12" height="14" rx="2" />
      <path d="M15 20H6a2 2 0 0 1-2-2V8M10 9h6M10 13h4" />
    </IconBase>
  );
}

export function QuizIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M7 3h10a2 2 0 0 1 2 2v16l-7-3-7 3V5a2 2 0 0 1 2-2Z" />
      <path d="M9.7 9a2.4 2.4 0 1 1 3.4 2.2c-.8.4-1.1.8-1.1 1.6M12 15.8h.01" />
    </IconBase>
  );
}

export function AudioIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M4 10v4M8 7v10M12 4v16M16 7v10M20 10v4" />
    </IconBase>
  );
}

export function MicrophoneIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <rect x="9" y="3" width="6" height="12" rx="3" />
      <path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.5 21h7" />
    </IconBase>
  );
}

export function UploadIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M12 16V4M7 9l5-5 5 5M5 20h14" />
    </IconBase>
  );
}

export function PlusIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M12 5v14M5 12h14" />
    </IconBase>
  );
}

export function TrashIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13M10 11v5M14 11v5" />
    </IconBase>
  );
}

export function PencilIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M4 20h4l11-11a2.8 2.8 0 0 0-4-4L4 16v4Z" />
      <path d="m13.5 6.5 4 4" />
    </IconBase>
  );
}

export function PanelToggleIcon({
  side,
  ...props
}: IconProps & { side: "left" | "right" }) {
  const dividerX = side === "left" ? 8 : 16;
  const panelX = side === "left" ? 3 : 16;

  return (
    <IconBase {...props}>
      <rect x="3" y="4" width="18" height="16" rx="2.5" />
      <path
        d={`M${panelX} 4h5v16h-5z`}
        fill="currentColor"
        opacity="0.12"
        stroke="none"
      />
      <path d={`M${dividerX} 4v16`} />
    </IconBase>
  );
}
