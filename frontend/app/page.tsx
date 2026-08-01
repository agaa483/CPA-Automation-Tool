import Link from "next/link";
import { SignedIn, SignedOut } from "@clerk/nextjs";

export default function Home() {
  return (
    <main className="min-h-screen flex items-center justify-center p-8">
      <div className="max-w-xl text-center space-y-6">
        <h1 className="text-4xl font-bold">QB Auditor</h1>
        <p className="text-lg text-gray-600">
          AI-powered audit layer for QuickBooks Online. Catches miscategorized
          transactions using email receipt evidence.
        </p>
        <div className="flex gap-3 justify-center">
          <SignedOut>
            <Link
              href="/sign-in"
              className="rounded-md bg-black px-6 py-3 text-white font-medium"
            >
              Sign in
            </Link>
            <Link
              href="/sign-up"
              className="rounded-md border border-black px-6 py-3 font-medium"
            >
              Sign up
            </Link>
          </SignedOut>
          <SignedIn>
            <Link
              href="/dashboard"
              className="rounded-md bg-black px-6 py-3 text-white font-medium"
            >
              Go to dashboard →
            </Link>
          </SignedIn>
        </div>
      </div>
    </main>
  );
}
