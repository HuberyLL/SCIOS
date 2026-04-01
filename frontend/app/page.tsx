import { AppHeader } from "@/components/app-header";
import { LandscapeWorkspace } from "@/components/landscape/landscape-workspace";

export default function Home() {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <AppHeader />
      <main className="flex-1">
        <LandscapeWorkspace />
      </main>
    </div>
  );
}
