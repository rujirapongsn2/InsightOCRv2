import Link from "next/link"
import { Sparkles, Code2, Check } from "lucide-react"
import { Button } from "@/components/ui/button"

export function ModeSelection() {
  return (
    <div className="max-w-5xl mx-auto space-y-8">
      <div className="text-center space-y-2">
        <h1 className="text-3xl font-bold tracking-tight text-slate-900">
          Create New Schema
        </h1>
        <p className="text-lg text-slate-600">
          Choose the mode that works best for you
        </p>
      </div>

      <div className="grid md:grid-cols-2 gap-6">
        {/* Simple Mode Card */}
        <div className="relative border-2 border-blue-200 rounded-xl p-8 bg-gradient-to-br from-blue-50 to-white hover:border-blue-300 transition-all hover:shadow-lg">
          <div className="absolute top-4 right-4">
            <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
              Recommended
            </span>
          </div>

          <div className="space-y-4">
            <div className="p-3 bg-blue-100 rounded-lg w-fit">
              <Sparkles className="h-8 w-8 text-blue-600" />
            </div>

            <div>
              <h2 className="text-2xl font-bold text-slate-900 mb-2">
                Simple Mode
              </h2>
              <p className="text-slate-600">
                Guided wizard with templates and AI assistance
              </p>
            </div>

            <ul className="space-y-3">
              {[
                "Step-by-step wizard",
                "Pre-built templates",
                "AI-powered field suggestions",
                "Live schema testing",
                "Helpful tips throughout"
              ].map((feature, index) => (
                <li key={index} className="flex items-center gap-2 text-sm text-slate-700">
                  <Check className="h-4 w-4 text-blue-600 flex-shrink-0" />
                  <span>{feature}</span>
                </li>
              ))}
            </ul>

            <Link href="/schemas/new/simple" className="block">
              <Button className="w-full mt-4 bg-blue-600 hover:bg-blue-700">
                Use Simple Mode
              </Button>
            </Link>

            <p className="text-xs text-center text-slate-500 mt-2">
              Perfect for beginners and quick schema creation
            </p>
          </div>
        </div>

        {/* Advanced Mode Card */}
        <div className="relative border-2 border-slate-200 rounded-xl p-8 bg-white hover:border-slate-300 transition-all hover:shadow-md">
          <div className="absolute top-4 right-4">
            <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium bg-amber-100 text-amber-800">
              Comming soon
            </span>
          </div>
          <div className="space-y-4">
            <div className="p-3 bg-slate-100 rounded-lg w-fit">
              <Code2 className="h-8 w-8 text-slate-600" />
            </div>

            <div>
              <h2 className="text-2xl font-bold text-slate-900 mb-2">
                Advanced Mode
              </h2>
              <p className="text-slate-600">
                Direct form access with full control
              </p>
            </div>

            <ul className="space-y-3">
              {[
                "Quick manual entry",
                "JSON Schema import",
                "No step-by-step process",
                "Full field control",
                "Faster for experienced users"
              ].map((feature, index) => (
                <li key={index} className="flex items-center gap-2 text-sm text-slate-700">
                  <Check className="h-4 w-4 text-slate-600 flex-shrink-0" />
                  <span>{feature}</span>
                </li>
              ))}
            </ul>

            <Button
              variant="outline"
              className="w-full mt-4 border-slate-300"
              disabled
            >
              Use Advanced Mode
            </Button>

            <p className="text-xs text-center text-slate-500 mt-2">
              For experienced users who know exactly what they need
            </p>
          </div>
        </div>
      </div>

      <div className="bg-slate-50 border border-slate-200 rounded-lg p-4">
        <p className="text-sm text-slate-600 text-center">
          <strong>Not sure which to choose?</strong> We recommend starting with Simple Mode.
          You can always use Advanced Mode later for quick edits.
        </p>
      </div>
    </div>
  )
}
