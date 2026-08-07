package com.example.data.mcp

import com.example.BuildConfig
import com.example.data.qubo.Constraint
import com.example.data.qubo.PolicyRule
import com.example.data.qubo.QuboSolution
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject

enum class McpEndpointType(val id: String, val displayName: String, val defaultUrl: String, val providerName: String) {
    DSG_BACKEND("dsg_backend", "DSG Backend Verification", BuildConfig.DSG_BACKEND_BASE_URL, "Server-side Z3 + MCP")
}

data class McpEndpointStatus(val endpointType: McpEndpointType, val isConnected: Boolean, val lastSyncTime: String?, val responseLatencyMs: Long, val lastStatusCode: Int, val activeToolsCount: Int)
data class McpDispatchResult(val success: Boolean, val endpoint: McpEndpointType, val timestamp: String, val payloadHash: String, val statusMessage: String, val rawJsonResponse: String, val httpStatusCode: Int, val z3Status: String?, val proofHash: String?, val auditEventHash: String?)

object McpGatewayEngine {
    val AVAILABLE_ENDPOINTS = listOf(McpEndpointType.DSG_BACKEND)
    private val jsonMediaType = "application/json; charset=utf-8".toMediaType()
    private val httpClient = OkHttpClient.Builder().connectTimeout(10, TimeUnit.SECONDS).readTimeout(30, TimeUnit.SECONDS).writeTimeout(15, TimeUnit.SECONDS).build()
    private fun normalizeBaseUrl(value: String): String = value.trim().trimEnd('/')

    private fun constraintJson(constraint: Constraint): JSONObject = JSONObject().apply {
        put("description", constraint.description)
        when (constraint) {
            is Constraint.Implication -> { put("type", "implication"); put("if_rule", constraint.ifRule); put("then_rule", constraint.thenRule) }
            is Constraint.Equivalence -> { put("type", "equivalence"); put("rules", JSONArray(constraint.rules)) }
            is Constraint.MinActive -> { put("type", "min_active"); put("minimum", constraint.minimum) }
            is Constraint.MaxCost -> { put("type", "max_cost"); put("budget", constraint.budget) }
            is Constraint.MutualExclusion -> { put("type", "mutual_exclusion"); put("rules", JSONArray(constraint.rules)) }
            is Constraint.AtLeastOneOf -> { put("type", "at_least_one_of"); put("rules", JSONArray(constraint.rules)) }
        }
    }

    fun buildVerificationRequestJson(presetName: String, solution: QuboSolution, rules: List<PolicyRule>, constraints: List<Constraint>): JSONObject = JSONObject().apply {
        put("request_id", UUID.randomUUID().toString())
        put("preset_name", presetName)
        put("configuration", JSONArray(solution.configuration))
        put("client_name", "dsg-android")
        put("client_version", BuildConfig.VERSION_NAME)
        put("rules", JSONArray().apply { rules.forEach { rule -> put(JSONObject().apply { put("id", rule.id); put("name", rule.name); put("cost", rule.cost); put("risk_reduction", rule.riskReduction); put("business_value", rule.businessValue); put("category", rule.category); put("description", rule.description) }) } })
        put("constraints", JSONArray().apply { constraints.forEach { put(constraintJson(it)) } })
        put("solver", JSONObject().apply { put("seed", solution.seed); put("iterations", solution.iterations); put("qubo_energy", solution.quboEnergy); put("solution_hash", solution.solutionHash) })
    }

    suspend fun dispatchToEndpoint(endpoint: McpEndpointType, presetName: String, solution: QuboSolution, rules: List<PolicyRule>, constraints: List<Constraint>): McpDispatchResult = withContext(Dispatchers.IO) {
        val timestamp = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault()).format(Date())
        val startedAt = System.nanoTime()
        val payload = buildVerificationRequestJson(presetName, solution, rules, constraints)
        val verifyUrl = "${normalizeBaseUrl(endpoint.defaultUrl)}/v1/verify"
        try {
            val requestBuilder = Request.Builder().url(verifyUrl).post(payload.toString().toRequestBody(jsonMediaType)).header("Accept", "application/json")
            if (BuildConfig.DSG_BACKEND_API_KEY.isNotBlank()) requestBuilder.header("X-API-Key", BuildConfig.DSG_BACKEND_API_KEY)
            httpClient.newCall(requestBuilder.build()).execute().use { response ->
                val elapsedMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - startedAt)
                val bodyText = response.body?.string().orEmpty()
                val responseJson = runCatching { JSONObject(bodyText) }.getOrNull()
                val z3Status = responseJson?.optString("z3_status")?.takeIf { it.isNotBlank() }
                val accepted = response.isSuccessful && responseJson?.optBoolean("accepted", false) == true
                val proofHash = responseJson?.optString("proof_hash")?.takeIf { it.isNotBlank() }
                val auditEventHash = responseJson?.optJSONObject("audit")?.optString("event_hash")?.takeIf { it.isNotBlank() }
                val errorDetail = responseJson?.optString("detail")?.takeIf { it.isNotBlank() }
                val statusMessage = when { accepted -> "Server-side Z3 verification SAT (${elapsedMs} ms)"; errorDetail != null -> "Backend rejected request: $errorDetail"; z3Status != null -> "Server-side Z3 verification $z3Status (${elapsedMs} ms)"; else -> "Backend returned HTTP ${response.code} (${elapsedMs} ms)" }
                McpDispatchResult(accepted, endpoint, timestamp, proofHash ?: solution.solutionHash, statusMessage, responseJson?.toString(2) ?: bodyText, response.code, z3Status, proofHash, auditEventHash)
            }
        } catch (error: Exception) {
            val errorJson = JSONObject().apply { put("error", error::class.java.simpleName); put("message", error.message ?: "Unknown backend error"); put("endpoint", verifyUrl) }
            McpDispatchResult(false, endpoint, timestamp, solution.solutionHash, "Backend request failed: ${error.message ?: error::class.java.simpleName}", errorJson.toString(2), 0, null, null, null)
        }
    }
}
