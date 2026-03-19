"use client";

import { useCallback, useState } from "react";
import { AppHeader } from "@/components/app-header";
import { SessionSidebar } from "@/components/assistant/session-sidebar";
import { ChatContainer } from "@/components/assistant/chat-container";
import { WorkspacePanel } from "@/components/assistant/workspace-panel";
import { useAssistantChat } from "@/hooks/use-assistant-chat";
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from "@/components/ui/resizable";

export default function AssistantPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);

  const {
    messages,
    activeArtifact,
    setActiveArtifact,
    isConnected,
    isLoading,
    error,
    sendMessage,
    reconnect,
  } = useAssistantChat(sessionId);

  const handleSelectSession = useCallback((id: string) => {
    setSessionId(id);
  }, []);

  const handleNewSession = useCallback((id: string) => {
    setSessionId(id);
  }, []);

  return (
    <div className="flex h-screen flex-col bg-background">
      <AppHeader />

      <div className="flex flex-1 overflow-hidden">
        <SessionSidebar
          currentSessionId={sessionId}
          onSelectSession={handleSelectSession}
          onNewSession={handleNewSession}
        />

        <main className="flex-1 overflow-hidden">
          {sessionId ? (
            <ResizablePanelGroup orientation="horizontal">
              <ResizablePanel defaultSize={60} minSize={35}>
                <ChatContainer
                  messages={messages}
                  isConnected={isConnected}
                  isLoading={isLoading}
                  error={error}
                  onSend={sendMessage}
                  onReconnect={reconnect}
                />
              </ResizablePanel>
              <ResizableHandle withHandle />
              <ResizablePanel defaultSize={40} minSize={20}>
                <WorkspacePanel
                  artifact={activeArtifact}
                  onClose={() => setActiveArtifact(null)}
                />
              </ResizablePanel>
            </ResizablePanelGroup>
          ) : (
            <div className="flex h-full items-center justify-center">
              <div className="text-center space-y-3">
                <div className="font-mono text-2xl font-bold tracking-wider text-foreground/20">
                  SCIOS
                </div>
                <p className="text-sm text-muted-foreground">
                  Create or select a session to start chatting.
                </p>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
