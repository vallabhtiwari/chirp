export default function Logo({ size = 28 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="var(--brand)" />
      <path d="M8 10h16v9H14l-5 4v-4H8z" fill="#fff" />
      <circle cx="13" cy="14.5" r="1.5" fill="var(--brand)" />
      <circle cx="19" cy="14.5" r="1.5" fill="var(--brand)" />
    </svg>
  )
}
