export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div
      className="flex min-h-screen items-center justify-center relative"
      style={{
        background: `
          radial-gradient(circle, rgba(156, 163, 175, 0.3) 1px, transparent 1px)
        `,
        backgroundSize: '24px 24px',
        backgroundPosition: '0 0',
      }}
    >
      {children}
    </div>
  );
}
