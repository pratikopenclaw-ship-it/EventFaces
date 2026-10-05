import { Poster } from "./poster";

export default async function PosterPage({ params }: PageProps<"/admin/events/[id]/poster">) {
  const { id } = await params;
  return <Poster id={id} />;
}
