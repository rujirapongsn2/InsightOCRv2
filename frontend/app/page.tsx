import Link from "next/link"
import { Logo } from "@/components/logo"
import { Button } from "@/components/ui/button"
import { ArrowRight } from "lucide-react"

export default function Home() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-slate-50">
      <div className="text-center space-y-6 p-8 max-w-2xl">
        <div className="flex justify-center mb-6">
          <Logo className="text-5xl" />
        </div>
        <p className="text-xl text-slate-600">
          Intelligent document processing platform. Extract data from invoices, receipts, and more with AI.
        </p>
        <div className="flex justify-center gap-4">
          <Link href="/dashboard">
            <Button size="lg">
              Go to Dashboard
              <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
          </Link>
          <Link href="/schemas">
            <Button variant="outline" size="lg">
              Manage Schemas
            </Button>
          </Link>
        </div>
      </div>
    </div>
  )
}
