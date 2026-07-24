<script setup lang="ts">
import { ref, watch } from 'vue'
import {
  createSkill,
  updateSkill,
  toast,
  type Skill,
  type SkillCategory,
} from '@aihelms/shared'
import IconPicker from '../../components/IconPicker.vue'

interface Props {
  visible: boolean
  editing: Skill | null
  categories: SkillCategory[]
}

const props = defineProps<Props>()
const emit = defineEmits<{
  close: []
  saved: [skill?: Skill]
}>()

// 镜像服务端 SKILLS_PACKAGE_MAX_TOTAL_SIZE_MB 默认值；服务端为准
const MAX_ZIP_SIZE = 100 * 1024 * 1024

const form = ref({
  name: '',
  icon_url: '/icons/v1/default.svg',
  description: '',
  author: '',
  category: 'general',
  version: '1.0.0',
  tags: '',
  usage_instructions: '',
  is_published: false,
  requires_approval: false,
  visibility_type: 'all',
  source_url: '',
})
const sourceMode = ref<'zip' | 'url'>('zip')
const zipFile = ref<File | null>(null)
const error = ref('')
const saving = ref(false)
const zipFileError = ref('')
const sourceUrlError = ref('')

function resetForm(): void {
  form.value = {
    name: '',
    icon_url: '/icons/v1/default.svg',
    description: '',
    author: '',
    category: props.categories[0]?.name || 'general',
    version: '1.0.0',
    tags: '',
    usage_instructions: '',
    is_published: false,
    requires_approval: false,
    visibility_type: 'all',
    source_url: '',
  }
  sourceMode.value = 'zip'
  zipFile.value = null
  zipFileError.value = ''
  sourceUrlError.value = ''
}

watch(
  () => props.visible,
  (v) => {
    if (!v) return
    error.value = ''
    if (props.editing) {
      const s = props.editing
      form.value = {
        name: s.name,
        icon_url: s.icon_url,
        description: s.description,
        author: s.author ?? '',
        category: s.category,
        version: s.version,
        tags: (s.tags || []).join(', '),
        usage_instructions: s.usage_instructions,
        is_published: s.is_published,
        requires_approval: s.requires_approval,
        visibility_type: s.visibility_type || 'all',
        source_url: '',
      }
    } else {
      resetForm()
    }
  },
)

function handleZipChange(event: Event): void {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0] || null
  zipFileError.value = ''
  if (file) {
    if (!file.name.toLowerCase().endsWith('.zip')) {
      zipFileError.value = '请上传 .zip 文件'
      zipFile.value = null
      return
    }
    if (file.size > MAX_ZIP_SIZE) {
      zipFileError.value = `文件超过 ${MAX_ZIP_SIZE / 1024 / 1024} MB 上限`
      zipFile.value = null
      return
    }
  }
  zipFile.value = file
}

async function handleSubmit(): Promise<void> {
  error.value = ''
  if (!form.value.name.trim()) {
    error.value = '请填写名称'
    return
  }
  if (zipFileError.value) {
    error.value = zipFileError.value
    return
  }
  saving.value = true
  try {
    const tags = form.value.tags
      ? form.value.tags.split(',').map((t) => t.trim()).filter(Boolean)
      : []
    const payload = {
      name: form.value.name.trim(),
      icon_url: form.value.icon_url,
      description: form.value.description,
      author: form.value.author,
      category: form.value.category,
      version: props.editing ? undefined : form.value.version,
      tags,
      usage_instructions: form.value.usage_instructions,
      is_published: form.value.is_published,
      requires_approval: form.value.requires_approval,
      visibility_type: form.value.visibility_type,
      zip_file: !props.editing && sourceMode.value === 'zip' ? zipFile.value : undefined,
      source_url: !props.editing && sourceMode.value === 'url' ? form.value.source_url : undefined,
    }
    if (props.editing) {
      const updated = await updateSkill(props.editing.id, payload)
      toast.success('Skill 更新成功')
      emit('saved', updated)
    } else {
      await createSkill(payload)
      toast.success('Skill 创建成功')
      emit('saved')
    }
  } catch (e) {
    error.value = (e as { message?: string }).message || '保存失败'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div
    v-if="visible"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/20"
  >
    <div
      class="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-2xl border border-slate-200/60 bg-white p-6 shadow-xl"
    >
      <h3 class="mb-4 text-lg font-semibold text-slate-900">
        {{ editing ? '编辑 Skill' : '新建 Skill' }}
      </h3>

      <div v-if="error" class="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">
        {{ error }}
      </div>

      <div class="grid grid-cols-2 gap-4">
        <div>
          <label class="mb-1 block text-sm font-medium text-slate-700">名称 *</label>
          <input
            v-model="form.name"
            class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
          />
        </div>
        <div>
          <IconPicker v-model="form.icon_url" label="图标" />
        </div>
        <div>
          <label class="mb-1 block text-sm font-medium text-slate-700">作者</label>
          <input
            v-model="form.author"
            class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
          />
        </div>
        <div>
          <label class="mb-1 block text-sm font-medium text-slate-700">分类</label>
          <select
            v-model="form.category"
            class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
          >
            <option v-for="c in categories" :key="c.id" :value="c.name">{{ c.name }}</option>
          </select>
        </div>
        <div>
          <label class="mb-1 block text-sm font-medium text-slate-700">版本</label>
          <input
            v-model="form.version"
            :disabled="!!editing"
            class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none disabled:bg-slate-50 disabled:text-slate-500"
          />
          <p v-if="editing" class="mt-1 text-xs text-slate-400">已存在 Skill 的版本由「版本管理」新增/激活</p>
          <p v-else class="mt-1 text-xs text-slate-400">初始版本号，如 1.0.0</p>
        </div>
        <div>
          <label class="mb-1 block text-sm font-medium text-slate-700">分类关键词（逗号分隔）</label>
          <input
            v-model="form.tags"
            class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
            placeholder="legal, ocr, markdown"
          />
        </div>
        <div class="col-span-2">
          <label class="mb-1 block text-sm font-medium text-slate-700">描述</label>
          <textarea
            v-model="form.description"
            rows="2"
            class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
          />
        </div>
        <div class="col-span-2">
          <label class="mb-1 block text-sm font-medium text-slate-700">使用说明（支持 Markdown）</label>
          <textarea
            v-model="form.usage_instructions"
            rows="4"
            class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs focus:border-purple-500 focus:outline-none"
          />
        </div>

        <!-- 来源方式：仅新建 -->
        <div v-if="!editing" class="col-span-2">
          <label class="mb-1 block text-sm font-medium text-slate-700">来源方式</label>
          <div class="mb-2 flex gap-2">
            <button
              type="button"
              :class="sourceMode === 'zip' ? 'rounded-lg bg-purple-600 px-3 py-1.5 text-xs font-medium text-white' : 'rounded-lg bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-200'"
              @click="sourceMode = 'zip'"
            >
              上传 zip 包
            </button>
            <button
              type="button"
              :class="sourceMode === 'url' ? 'rounded-lg bg-purple-600 px-3 py-1.5 text-xs font-medium text-white' : 'rounded-lg bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-200'"
              @click="sourceMode = 'url'"
            >
              仓库 URL
            </button>
          </div>
          <template v-if="sourceMode === 'zip'">
            <input
              type="file"
              accept=".zip"
              class="block w-full text-sm text-slate-700 file:mr-3 file:rounded-md file:border-0 file:bg-purple-50 file:px-3 file:py-2 file:text-sm file:font-medium file:text-purple-700 hover:file:bg-purple-100"
              @change="handleZipChange"
            />
            <p v-if="zipFile" class="mt-1 text-xs text-slate-500">
              已选择：{{ zipFile.name }} ({{ Math.round(zipFile.size / 1024) }} KB)
            </p>
            <p v-if="zipFileError" class="mt-1 text-xs text-red-500">{{ zipFileError }}</p>
            <p class="mt-1 text-xs text-slate-400">
              允许的文件类型：md/json/txt/py/js/sh/yaml/csv/png/jpg/svg/pdf 等；单文件 ≤10MB，总包 ≤100MB，最多 500 文件
            </p>
          </template>
          <template v-else>
            <input
              v-model="form.source_url"
              class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
              placeholder="https://github.com/owner/repo/tree/main"
              @input="sourceUrlError = ''"
            />
            <p v-if="sourceUrlError" class="mt-1 text-xs text-red-500">{{ sourceUrlError }}</p>
            <p class="mt-1 text-[11px] text-slate-400">
              支持的仓库：GitHub、Gitee、GitLab（需管理员配置白名单域名）
            </p>
          </template>
        </div>

        <div class="col-span-2">
          <label class="mb-1 block text-sm font-medium text-slate-700">可见性</label>
          <select
            v-model="form.visibility_type"
            class="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
          >
            <option value="all">公开（进入市场列表）</option>
            <option value="private">仅创建者（私有）</option>
            <option value="unlisted">不列出（仅直链可访问）</option>
          </select>
          <p class="mt-1 text-xs text-slate-400">
            private 仅创建者和管理员可见；unlisted 不进市场列表，持有直链的登录用户可查看详情
          </p>
        </div>
        <div class="col-span-2 flex items-center gap-4">
          <label class="flex items-center gap-2 text-sm text-slate-700">
            <input v-model="form.is_published" type="checkbox" class="h-4 w-4 rounded border-slate-300" />
            发布到用户端
          </label>
          <label class="flex items-center gap-2 text-sm text-slate-700">
            <input
              v-model="form.requires_approval"
              type="checkbox"
              :disabled="!form.is_published"
              class="h-4 w-4 rounded border-slate-300 disabled:opacity-50"
            />
            领用前需要审批
          </label>
        </div>
      </div>

      <div class="mt-6 flex justify-end gap-3">
        <button
          class="rounded-lg bg-slate-100 px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-200"
          :disabled="saving"
          @click="emit('close')"
        >
          取消
        </button>
        <button
          class="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-purple-700 disabled:opacity-50"
          :disabled="saving"
          @click="handleSubmit"
        >
          {{ saving ? '保存中...' : '保存' }}
        </button>
      </div>
    </div>
  </div>
</template>
