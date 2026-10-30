"use client"

import { useParams, useRouter } from "next/navigation"
import { SchemaEditor } from "@/components/schema/SchemaEditor"

export default function EditSchemaPage() {
  const params = useParams<{ id: string }>()
  const router = useRouter()
  return <SchemaEditor schemaId={params.id} embedded={false} onClose={() => router.push("/schemas")} onSaved={() => router.push("/schemas")} />
}
