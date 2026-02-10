# Integration Database Migration Guide

## ✅ Backend Implementation Complete!

### What Has Been Created:

**1. Database Model**
- ✅ `backend/app/models/integration.py` - Integration model with full schema
- ✅ `backend/app/models/user.py` - Added integrations relationship
- ✅ Table will be auto-created on next backend restart

**2. API Schemas**
- ✅ `backend/app/schemas/integration.py` - Pydantic schemas for validation

**3. CRUD Operations**
- ✅ `backend/app/crud/crud_integration.py` - Database operations

**4. API Endpoints**
- ✅ `GET /api/v1/integrations` - Get all integrations
- ✅ `GET /api/v1/integrations/active` - Get active integrations
- ✅ `GET /api/v1/integrations/{id}` - Get specific integration
- ✅ `POST /api/v1/integrations` - Create integration
- ✅ `PUT /api/v1/integrations/{id}` - Update integration
- ✅ `DELETE /api/v1/integrations/{id}` - Delete integration

**5. Frontend API Client**
- ✅ `frontend/lib/integrations-api.ts` - TypeScript API client functions

---

## 🔄 Database Schema

```sql
CREATE TABLE integrations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id),
    name VARCHAR(255) NOT NULL,
    type VARCHAR(20) NOT NULL CHECK (type IN ('api', 'workflow', 'llm')),
    description TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused')),
    config JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_integrations_user_id ON integrations(user_id);
CREATE INDEX idx_integrations_status ON integrations(status);
```

---

## 📝 Frontend Migration Steps

### Step 1: Update Integrations Page

Replace localStorage calls with API calls in `frontend/app/(dashboard)/integrations/page.tsx`:

**Before (localStorage):**
```typescript
// Load from localStorage
useEffect(() => {
    const stored = localStorage.getItem("integrations")
    if (stored) {
        setIntegrations(JSON.parse(stored))
    }
}, [])

// Save to localStorage
const persistIntegrations = (items: Integration[]) => {
    setIntegrations(items)
    localStorage.setItem("integrations", JSON.stringify(items))
}
```

**After (API):**
```typescript
import { getIntegrations, createIntegration, updateIntegration, deleteIntegration } from "@/lib/integrations-api"
import { useAuth } from "@/components/auth-provider"

const { token } = useAuth()

// Load from API
useEffect(() => {
    if (!token) return

    const loadIntegrations = async () => {
        try {
            const data = await getIntegrations(token)
            setIntegrations(data.integrations)
        } catch (error) {
            console.error("Failed to load integrations:", error)
        }
    }

    loadIntegrations()
}, [token])

// Create integration via API
const handleCreate = async (data: IntegrationCreate) => {
    try {
        const newIntegration = await createIntegration(token, data)
        setIntegrations([...integrations, newIntegration])
    } catch (error) {
        console.error("Failed to create integration:", error)
    }
}

// Update integration via API
const handleUpdate = async (id: string, data: IntegrationUpdate) => {
    try {
        const updated = await updateIntegration(token, id, data)
        setIntegrations(integrations.map(i => i.id === id ? updated : i))
    } catch (error) {
        console.error("Failed to update integration:", error)
    }
}

// Delete integration via API
const handleDelete = async (id: string) => {
    try {
        await deleteIntegration(token, id)
        setIntegrations(integrations.filter(i => i.id !== id))
    } catch (error) {
        console.error("Failed to delete integration:", error)
    }
}
```

### Step 2: Update Job Detail Page

Replace localStorage with API in `frontend/app/(dashboard)/jobs/[id]/page.tsx`:

**Before:**
```typescript
const loadIntegrations = () => {
    const stored = localStorage.getItem("integrations")
    if (stored) {
        const parsed = JSON.parse(stored)
        setIntegrations(parsed.filter(int => int.status === "active"))
    }
}
```

**After:**
```typescript
import { getActiveIntegrations } from "@/lib/integrations-api"

const loadIntegrations = async () => {
    if (!token) return

    try {
        const activeIntegrations = await getActiveIntegrations(token)
        setIntegrations(activeIntegrations)
    } catch (error) {
        console.error("Failed to load integrations:", error)
    }
}

useEffect(() => {
    loadIntegrations()
}, [token])
```

---

## 🚀 Deployment Steps

### 1. Restart Backend to Create Table

```bash
# Stop backend
docker compose restart backend

# Wait for backend to start and create table
docker logs -f softnix_ocr_backend
```

Expected log output:
```
INFO:     Application startup complete.
```

### 2. Verify Table Creation

```bash
# Connect to database
docker exec -it softnix_ocr_db psql -U postgres -d softnix_ocr

# Check if table exists
\dt integrations

# Check table structure
\d integrations

# Exit
\q
```

### 3. Test API Endpoints

```bash
# Get token
TOKEN="your-jwt-token"

# Test GET /integrations
curl -k -X GET https://localhost/api/v1/integrations \
  -H "Authorization: Bearer $TOKEN"

# Test POST /integrations
curl -k -X POST https://localhost/api/v1/integrations \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Integration",
    "type": "api",
    "description": "Test integration via API",
    "status": "active",
    "config": {
      "endpoint": "https://example.com/api",
      "method": "POST"
    }
  }'
```

---

## 🔄 Data Migration (localStorage → Database)

### Option 1: Manual Migration Script

Create `frontend/scripts/migrate-integrations.ts`:

```typescript
import { getIntegrations, createIntegration } from "@/lib/integrations-api"

async function migrateLocalStorageToDatabase() {
  const token = prompt("Enter your auth token:")
  if (!token) return

  // Read from localStorage
  const stored = localStorage.getItem("integrations")
  if (!stored) {
    console.log("No integrations found in localStorage")
    return
  }

  const localIntegrations = JSON.parse(stored)
  console.log(`Found ${localIntegrations.length} integrations in localStorage`)

  // Create each integration in database
  for (const integration of localIntegrations) {
    try {
      await createIntegration(token, {
        name: integration.name,
        type: integration.type,
        description: integration.description,
        status: integration.status,
        config: integration.config
      })
      console.log(`✓ Migrated: ${integration.name}`)
    } catch (error) {
      console.error(`✗ Failed to migrate: ${integration.name}`, error)
    }
  }

  console.log("Migration complete!")
  console.log("You can now clear localStorage if desired")
}

// Run migration
migrateLocalStorageToDatabase()
```

### Option 2: Automatic Migration in Component

Add to `frontend/app/(dashboard)/integrations/page.tsx`:

```typescript
useEffect(() => {
  const migrateFromLocalStorage = async () => {
    if (!token) return

    // Check if already migrated
    const migrated = localStorage.getItem("integrations_migrated")
    if (migrated) return

    // Get localStorage data
    const stored = localStorage.getItem("integrations")
    if (!stored) {
      localStorage.setItem("integrations_migrated", "true")
      return
    }

    try {
      const localIntegrations = JSON.parse(stored)

      // Check if database is empty
      const { integrations: dbIntegrations } = await getIntegrations(token)
      if (dbIntegrations.length > 0) {
        // Database already has data, skip migration
        localStorage.setItem("integrations_migrated", "true")
        return
      }

      // Migrate each integration
      for (const integration of localIntegrations) {
        await createIntegration(token, {
          name: integration.name,
          type: integration.type,
          description: integration.description,
          status: integration.status,
          config: integration.config
        })
      }

      // Mark as migrated
      localStorage.setItem("integrations_migrated", "true")
      console.log("Successfully migrated integrations from localStorage to database")

      // Optionally clear localStorage
      // localStorage.removeItem("integrations")
    } catch (error) {
      console.error("Failed to migrate integrations:", error)
    }
  }

  migrateFromLocalStorage()
}, [token])
```

---

## ✅ Testing Checklist

### Backend Tests

- [ ] Table `integrations` created successfully
- [ ] Can create integration via API
- [ ] Can read integrations via API
- [ ] Can update integration via API
- [ ] Can delete integration via API
- [ ] User can only access their own integrations
- [ ] Activity logs are created for CRUD operations

### Frontend Tests

- [ ] Integrations page loads data from API
- [ ] Can create new integration (saves to database)
- [ ] Can edit existing integration (updates database)
- [ ] Can delete integration (removes from database)
- [ ] Job detail page loads active integrations from API
- [ ] Send to Integration still works with API data
- [ ] No localStorage references remain

---

## 🔐 Security Improvements

### Current Implementation

- ✅ API keys stored in database (server-side)
- ✅ User authentication required
- ✅ User can only access their own integrations
- ✅ Activity logging for audit trail

### Next Steps (Optional)

1. **Encrypt sensitive fields in database:**
   ```python
   from cryptography.fernet import Fernet

   # In integration model
   def set_api_key(self, api_key: str, encryption_key: str):
       f = Fernet(encryption_key)
       self.config["apiKey"] = f.encrypt(api_key.encode()).decode()

   def get_api_key(self, encryption_key: str) -> str:
       f = Fernet(encryption_key)
       return f.decrypt(self.config["apiKey"].encode()).decode()
   ```

2. **Add field-level encryption:**
   - Encrypt: `apiKey`, `authHeader`, `webhookUrl`
   - Leave unencrypted: `endpoint`, `method`, `instructions`

---

## 📊 Benefits of Database Storage

### Before (localStorage):
- ❌ Per-browser storage (not synced)
- ❌ No backup
- ❌ API keys visible in DevTools
- ❌ Lost on cache clear
- ❌ No audit trail
- ❌ No sharing between users

### After (Database):
- ✅ Centralized storage
- ✅ Automatic backup
- ✅ API keys server-side
- ✅ Persistent storage
- ✅ Full audit trail
- ✅ Can implement sharing/templates

---

## 🔄 Rollback Plan

If you need to rollback:

1. **Comment out Integration routes in API:**
   ```python
   # In backend/app/api/v1/endpoints/integrations.py
   # Comment out all @router.get/post/put/delete decorators
   ```

2. **Revert frontend to localStorage:**
   ```bash
   git checkout frontend/app/\(dashboard\)/integrations/page.tsx
   git checkout frontend/app/\(dashboard\)/jobs/[id]/page.tsx
   ```

3. **Drop table (if needed):**
   ```sql
   DROP TABLE integrations;
   ```

---

**Last Updated:** 2025-12-22
**Status:** ✅ Backend Complete | ⏳ Frontend Pending
**Next Step:** Update frontend components to use API
