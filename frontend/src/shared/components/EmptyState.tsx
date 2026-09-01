interface Props {
  message: string;
  action?: React.ReactNode;
}

export function EmptyState({ message, action }: Props) {
  return (
    <div className="empty-state stack" style={{ alignItems: "center" }}>
      <div>{message}</div>
      {action}
    </div>
  );
}
