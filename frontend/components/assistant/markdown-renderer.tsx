"use client";

import { useCallback, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { Check, Copy } from "lucide-react";
import { cn } from "@/lib/utils";
import "katex/dist/katex.min.css";

interface MarkdownRendererProps {
  content: string;
  className?: string;
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [text]);

  return (
    <button
      onClick={handleCopy}
      className="absolute right-2 top-2 flex h-7 w-7 items-center justify-center rounded-md bg-white/10 text-white/60 transition-colors hover:bg-white/20 hover:text-white"
    >
      {copied ? (
        <Check className="h-3.5 w-3.5" />
      ) : (
        <Copy className="h-3.5 w-3.5" />
      )}
    </button>
  );
}

export function MarkdownRenderer({ content, className }: MarkdownRendererProps) {
  return (
    <div className={cn("prose-academic text-sm leading-relaxed", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          code({ className: codeClassName, children, ...props }) {
            const match = /language-(\w+)/.exec(codeClassName || "");
            const codeString = String(children).replace(/\n$/, "");

            if (match) {
              return (
                <div className="relative my-3 overflow-hidden rounded-lg">
                  <div className="flex items-center justify-between bg-zinc-800 px-4 py-1.5">
                    <span className="text-[10px] font-medium uppercase tracking-wider text-zinc-400">
                      {match[1]}
                    </span>
                  </div>
                  <CopyButton text={codeString} />
                  <SyntaxHighlighter
                    style={oneDark}
                    language={match[1]}
                    PreTag="div"
                    customStyle={{
                      margin: 0,
                      borderTopLeftRadius: 0,
                      borderTopRightRadius: 0,
                      fontSize: "0.8rem",
                    }}
                  >
                    {codeString}
                  </SyntaxHighlighter>
                </div>
              );
            }

            return (
              <code
                className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs"
                {...props}
              >
                {children}
              </code>
            );
          },

          table({ children }) {
            return (
              <div className="my-3 overflow-x-auto rounded-lg border border-border">
                <table className="w-full text-xs">{children}</table>
              </div>
            );
          },
          thead({ children }) {
            return <thead className="bg-muted/50">{children}</thead>;
          },
          th({ children }) {
            return (
              <th className="border-b border-border px-3 py-2 text-left font-medium text-foreground">
                {children}
              </th>
            );
          },
          td({ children }) {
            return (
              <td className="border-b border-border/50 px-3 py-2 text-muted-foreground">
                {children}
              </td>
            );
          },

          a({ href, children }) {
            return (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary underline underline-offset-2 hover:text-primary/80"
              >
                {children}
              </a>
            );
          },

          p({ children }) {
            return <p className="mb-3 last:mb-0">{children}</p>;
          },

          ul({ children }) {
            return <ul className="mb-3 ml-4 list-disc space-y-1">{children}</ul>;
          },
          ol({ children }) {
            return (
              <ol className="mb-3 ml-4 list-decimal space-y-1">{children}</ol>
            );
          },
          li({ children }) {
            return <li className="text-sm">{children}</li>;
          },

          blockquote({ children }) {
            return (
              <blockquote className="my-3 border-l-2 border-primary/30 pl-4 italic text-muted-foreground">
                {children}
              </blockquote>
            );
          },

          h1({ children }) {
            return (
              <h1 className="mb-3 mt-5 text-xl font-semibold">{children}</h1>
            );
          },
          h2({ children }) {
            return (
              <h2 className="mb-2 mt-4 text-lg font-semibold">{children}</h2>
            );
          },
          h3({ children }) {
            return (
              <h3 className="mb-2 mt-3 text-base font-semibold">{children}</h3>
            );
          },

          hr() {
            return <hr className="my-4 border-border/50" />;
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
