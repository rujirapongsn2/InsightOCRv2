"use client"

import { useState } from "react"
import { Check, X, Edit2, Sparkles } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { SuggestedField, FieldType } from "@/types/schema"

interface SuggestedFieldCardProps {
  field: SuggestedField
  onAccept: (field: SuggestedField) => void
  onReject: (fieldName: string) => void
  disabled?: boolean
  isAccepted?: boolean
}

const FIELD_TYPE_OPTIONS: Array<{ value: FieldType; label: string }> = [
  { value: "text", label: "Text" },
  { value: "number", label: "Number" },
  { value: "date", label: "Date" },
  { value: "currency", label: "Currency" },
  { value: "boolean", label: "Yes/No" }
]

export function SuggestedFieldCard({ field, onAccept, onReject, disabled, isAccepted = false }: SuggestedFieldCardProps) {
  const [isEditing, setIsEditing] = useState(false)
  const [editedField, setEditedField] = useState<SuggestedField>(field)

  const handleAccept = () => {
    onAccept(isEditing ? editedField : field)
    setIsEditing(false)  // Exit edit mode after accepting
  }

  const confidenceColor =
    field.confidence >= 0.8 ? "text-green-600 bg-green-50" :
    field.confidence >= 0.6 ? "text-yellow-600 bg-yellow-50" :
    "text-orange-600 bg-orange-50"

  const confidencePercentage = Math.round(field.confidence * 100)

  return (
    <div className={`border rounded-lg p-4 transition-all ${
      isAccepted
        ? "border-green-500 bg-green-50/50 shadow-sm"
        : "border-blue-200 bg-blue-50/30 hover:bg-blue-50/50"
    }`}>
      {/* Header with confidence badge */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          {isAccepted ? (
            <Check className="h-4 w-4 text-green-600" />
          ) : (
            <Sparkles className="h-4 w-4 text-blue-600" />
          )}
          <span className="font-medium text-slate-900">{field.name}</span>
          {isAccepted && (
            <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
              Accepted
            </span>
          )}
        </div>
        <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${confidenceColor}`}>
          {confidencePercentage}% confident
        </span>
      </div>

      {!isEditing ? (
        <>
          {/* View Mode */}
          <div className="space-y-2 mb-4">
            <div className="text-sm">
              <span className="text-slate-500">Type:</span>{" "}
              <span className="font-medium text-slate-700 capitalize">{field.type}</span>
            </div>
            <div className="text-sm">
              <span className="text-slate-500">Description:</span>{" "}
              <span className="text-slate-700">{field.description}</span>
            </div>
            {field.example_value && (
              <div className="text-sm">
                <span className="text-slate-500">Example:</span>{" "}
                <span className="text-slate-700 font-mono bg-white px-2 py-0.5 rounded">
                  {field.example_value}
                </span>
              </div>
            )}
            <div className="text-sm">
              <span className="text-slate-500">Required:</span>{" "}
              <span className="text-slate-700">{field.required ? "Yes" : "No"}</span>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex items-center gap-2">
            {!isAccepted ? (
              <Button
                size="sm"
                onClick={handleAccept}
                disabled={disabled}
                className="flex-1"
              >
                <Check className="h-3 w-3 mr-1" />
                Accept
              </Button>
            ) : (
              <Button
                size="sm"
                variant="outline"
                disabled
                className="flex-1 bg-green-50 border-green-300 text-green-700"
              >
                <Check className="h-3 w-3 mr-1" />
                Accepted
              </Button>
            )}
            <Button
              size="sm"
              variant="outline"
              onClick={() => setIsEditing(true)}
              disabled={disabled}
            >
              <Edit2 className="h-3 w-3 mr-1" />
              Edit
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => onReject(field.name)}
              disabled={disabled}
              className="text-red-600 hover:text-red-700 hover:bg-red-50"
            >
              <X className="h-3 w-3" />
            </Button>
          </div>
        </>
      ) : (
        <>
          {/* Edit Mode */}
          <div className="space-y-3 mb-4">
            {/* Field Name */}
            <div>
              <label className="text-xs font-medium text-slate-600">Field Name</label>
              <Input
                value={editedField.name || ""}
                onChange={(e) => setEditedField({ ...editedField, name: e.target.value })}
                className="mt-1 text-sm"
                placeholder="field_name"
              />
            </div>

            {/* Field Type */}
            <div>
              <label className="text-xs font-medium text-slate-600">Type</label>
              <select
                value={editedField.type}
                onChange={(e) => setEditedField({ ...editedField, type: e.target.value as FieldType })}
                className="w-full mt-1 px-3 py-2 text-sm border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {FIELD_TYPE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Description */}
            <div>
              <label className="text-xs font-medium text-slate-600">Description</label>
              <Input
                value={editedField.description || ""}
                onChange={(e) => setEditedField({ ...editedField, description: e.target.value })}
                className="mt-1 text-sm"
                placeholder="Description"
              />
            </div>

            {/* Required Checkbox */}
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={editedField.required}
                onChange={(e) => setEditedField({ ...editedField, required: e.target.checked })}
                className="w-4 h-4 text-blue-600 border-slate-300 rounded focus:ring-blue-500"
              />
              <span className="text-sm text-slate-700">Required field</span>
            </label>
          </div>

          {/* Edit Action Buttons */}
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              onClick={() => {
                setIsEditing(false)
                handleAccept()
              }}
              disabled={disabled}
              className="flex-1"
            >
              <Check className="h-3 w-3 mr-1" />
              Accept Changes
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setEditedField(field)
                setIsEditing(false)
              }}
              disabled={disabled}
            >
              Cancel
            </Button>
          </div>
        </>
      )}
    </div>
  )
}
