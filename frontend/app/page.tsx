import { AppHeader } from "@/components/app-header";
import { LandscapeWorkspace } from "@/components/landscape/landscape-workspace";

export default function Home() {
  return (
    <div className="flex h-screen flex-col bg-background">
      <AppHeader />
      <main className="flex-1 overflow-hidden">
        <LandscapeWorkspace />
      </main>
    </div>
  );
}
