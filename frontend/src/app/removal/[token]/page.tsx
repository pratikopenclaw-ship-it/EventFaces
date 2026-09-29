import { RemovalSubmit } from "./removal-submit";

export default async function RemovalTokenPage({ params }: PageProps<"/removal/[token]">) {
  const { token } = await params;
  return <RemovalSubmit token={token} />;
}
