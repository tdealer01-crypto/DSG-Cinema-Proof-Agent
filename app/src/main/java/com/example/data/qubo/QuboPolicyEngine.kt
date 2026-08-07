package com.example.data.qubo

import java.security.MessageDigest

/**
 * Deterministic QUBO policy engine for the Android companion client.
 *
 * Presets in this app are small (<= 12 variables), so v4 enumerates the bounded binary
 * state space instead of pretending a local Boolean check is Z3. Server-side Z3 remains
 * authoritative and is called through McpGatewayEngine before a formal-verification claim.
 */
object QuboPolicyEngine {
    val FINTECH_RULES = listOf(
        PolicyRule(0, "MFA_REQUIRED", 200.0, 30.0, 50.0, "IDENTITY"),
        PolicyRule(1, "IP_WHITELIST", 100.0, 20.0, 30.0, "NETWORK"),
        PolicyRule(2, "RATE_LIMIT_API", 150.0, 25.0, 40.0, "NETWORK"),
        PolicyRule(3, "ENCRYPTION_AT_REST", 300.0, 40.0, 60.0, "DATA_PROTECTION"),
        PolicyRule(4, "ENCRYPTION_IN_TRANSIT", 250.0, 35.0, 55.0, "DATA_PROTECTION"),
        PolicyRule(5, "AUDIT_LOG_ALL", 180.0, 15.0, 35.0, "MONITORING"),
        PolicyRule(6, "DLP_EMAIL", 220.0, 20.0, 25.0, "DATA_PROTECTION"),
        PolicyRule(7, "ZERO_TRUST_NETWORK", 500.0, 50.0, 80.0, "NETWORK"),
        PolicyRule(8, "SOC2_COMPLIANCE", 400.0, 35.0, 70.0, "COMPLIANCE"),
        PolicyRule(9, "PENETRATION_TEST_QUARTERLY", 350.0, 30.0, 45.0, "COMPLIANCE"),
        PolicyRule(10, "INCIDENT_RESPONSE_PLAN", 120.0, 10.0, 20.0, "INCIDENT_RESPONSE"),
        PolicyRule(11, "EMPLOYEE_SECURITY_TRAINING", 80.0, 15.0, 25.0, "TRAINING")
    )
    val FINTECH_CONSTRAINTS = listOf<Constraint>(
        Constraint.Implication(7, 0, "Zero Trust requires MFA"),
        Constraint.Equivalence(listOf(3, 4), "Encryption must be both at-rest and in-transit"),
        Constraint.Implication(8, 5, "SOC2 requires Audit Logging"),
        Constraint.MinActive(4, "At least 4 security controls required"),
        Constraint.MaxCost(1500.0, "Annual security budget 1500"),
        Constraint.Implication(9, 10, "Pen Testing requires Incident Response Plan")
    )

    val EU_GDPR_AI_ACT_RULES = listOf(
        PolicyRule(0, "GDPR_CONSENT_ART6", 150.0, 30.0, 50.0, "COMPLIANCE"),
        PolicyRule(1, "GDPR_ERASURE_ART17", 200.0, 25.0, 40.0, "DATA_PROTECTION"),
        PolicyRule(2, "GDPR_DPO_ART37", 250.0, 35.0, 60.0, "IDENTITY"),
        PolicyRule(3, "GDPR_DPIA_ART35", 300.0, 45.0, 70.0, "MONITORING"),
        PolicyRule(4, "EU_AI_ACT_HIGH_RISK", 400.0, 60.0, 85.0, "COMPLIANCE"),
        PolicyRule(5, "EU_AI_ACT_OVERSIGHT", 350.0, 50.0, 80.0, "INCIDENT_RESPONSE"),
        PolicyRule(6, "EU_AI_ACT_TRANSPARENCY", 220.0, 35.0, 50.0, "TRAINING")
    )
    val EU_GDPR_AI_ACT_CONSTRAINTS = listOf<Constraint>(
        Constraint.Implication(4, 3, "High-risk AI requires DPIA"),
        Constraint.Implication(4, 2, "High-risk AI requires DPO oversight"),
        Constraint.Implication(5, 6, "Human oversight requires transparency docs"),
        Constraint.MinActive(3, "At least 3 core EU safeguards"),
        Constraint.MaxCost(1500.0, "EU compliance budget cap")
    )

    val THAI_PDPA_RULES = listOf(
        PolicyRule(0, "PDPA_CONSENT_SEC19", 120.0, 30.0, 45.0, "COMPLIANCE"),
        PolicyRule(1, "PDPA_RIGHTS_SEC30", 180.0, 25.0, 40.0, "DATA_PROTECTION"),
        PolicyRule(2, "PDPA_SECURITY_SEC37", 250.0, 40.0, 60.0, "DATA_PROTECTION"),
        PolicyRule(3, "PDPA_BREACH_NOTIFY_SEC37", 200.0, 35.0, 50.0, "INCIDENT_RESPONSE"),
        PolicyRule(4, "PDPA_DPO_SEC41", 220.0, 30.0, 55.0, "IDENTITY")
    )
    val THAI_PDPA_CONSTRAINTS = listOf<Constraint>(
        Constraint.Implication(3, 2, "Breach notification requires security controls"),
        Constraint.Implication(1, 0, "Data-subject rights require consent basis"),
        Constraint.MinActive(2, "At least 2 PDPA safeguards"),
        Constraint.MaxCost(800.0, "PDPA budget cap")
    )

    val CRIMINAL_LAW_RULES = listOf(
        PolicyRule(0, "COMMITTED_ACT", 100.0, 10.0, 20.0, "DEMO"),
        PolicyRule(1, "INTENTIONAL_M59", 200.0, 10.0, 30.0, "DEMO"),
        PolicyRule(2, "NEGLIGENT_M59", 150.0, 10.0, 20.0, "DEMO"),
        PolicyRule(3, "SELF_DEFENSE_M68", 50.0, 80.0, 90.0, "DEMO"),
        PolicyRule(4, "NECESSITY_M67", 80.0, 60.0, 70.0, "DEMO"),
        PolicyRule(5, "PROVOCATION_M72", 70.0, 40.0, 50.0, "DEMO"),
        PolicyRule(6, "COMPENSATION_M78", 100.0, 30.0, 60.0, "DEMO"),
        PolicyRule(7, "INFANT_UNDER_12_M73", 30.0, 90.0, 80.0, "DEMO")
    )
    val CRIMINAL_LAW_CONSTRAINTS = listOf<Constraint>(
        Constraint.MutualExclusion(listOf(1, 2), "Intent and negligence are mutually exclusive in this simplified demo"),
        Constraint.Implication(3, 0, "Self-defense analysis requires an act"),
        Constraint.MutualExclusion(listOf(3, 4), "Simplified demo keeps self-defense and necessity exclusive"),
        Constraint.MinActive(2, "Evaluate at least two conditions"),
        Constraint.MaxCost(1000.0, "Demo budget cap")
    )

    fun buildQUBOMatrix(rules: List<PolicyRule>, constraints: List<Constraint>, penaltyWeight: Double): List<List<Double>> {
        val n = rules.size
        val q = Array(n) { DoubleArray(n) }
        rules.forEachIndexed { i, rule -> q[i][i] = -(rule.businessValue + rule.riskReduction) }
        constraints.forEach { constraint ->
            when (constraint) {
                is Constraint.Implication -> { q[constraint.ifRule][constraint.ifRule] += penaltyWeight; q[constraint.ifRule][constraint.thenRule] -= penaltyWeight }
                is Constraint.Equivalence -> constraint.rules.zipWithNext().forEach { (a, b) -> q[a][a] += penaltyWeight; q[b][b] += penaltyWeight; q[a][b] -= 2 * penaltyWeight }
                is Constraint.MutualExclusion -> constraint.rules.forEachIndexed { i, a -> constraint.rules.drop(i + 1).forEach { b -> q[a][b] += penaltyWeight } }
                is Constraint.AtLeastOneOf -> constraint.rules.forEach { q[it][it] -= penaltyWeight * 0.1 }
                is Constraint.MinActive, is Constraint.MaxCost -> Unit
            }
        }
        return q.map { it.toList() }
    }

    fun computeEnergy(x: List<Int>, q: List<List<Double>>): Double = x.indices.sumOf { i -> x.indices.sumOf { j -> q[i][j] * x[i] * x[j] } }

    fun verifyConstraints(x: List<Int>, rules: List<PolicyRule>, constraints: List<Constraint>): List<ConstraintResult> = constraints.map { c ->
        val (ok, detail) = when (c) {
            is Constraint.Implication -> (((x[c.ifRule] == 0) || x[c.thenRule] == 1) to "${c.ifRule} -> ${c.thenRule}")
            is Constraint.Equivalence -> (c.rules.map { x[it] }.distinct().size <= 1 to "equal states: ${c.rules}")
            is Constraint.MinActive -> (x.sum() >= c.minimum to "active=${x.sum()}, minimum=${c.minimum}")
            is Constraint.MaxCost -> {
                val cost = x.indices.sumOf { i -> x[i] * rules[i].cost }
                (cost <= c.budget to "cost=$cost, budget=${c.budget}")
            }
            is Constraint.MutualExclusion -> (c.rules.sumOf { x[it] } <= 1 to "at most one: ${c.rules}")
            is Constraint.AtLeastOneOf -> (c.rules.any { x[it] == 1 } to "at least one: ${c.rules}")
        }
        ConstraintResult(c, ok, if (c.description.isBlank()) detail else "[${c.description}] $detail")
    }

    fun solve(rules: List<PolicyRule>, constraints: List<Constraint>, config: EngineConfig): QuboSolution {
        require(rules.size <= 20) { "Android exact solver is bounded to 20 binary variables" }
        val q = buildQUBOMatrix(rules, constraints, config.penaltyWeight)
        val states = 1 shl rules.size
        val limit = minOf(states, maxOf(1, config.maxIterations))
        var best: List<Int>? = null
        var bestEnergy = Double.POSITIVE_INFINITY
        var evaluated = 0
        for (mask in 0 until limit) {
            val x = List(rules.size) { index -> (mask shr index) and 1 }
            evaluated++
            if (verifyConstraints(x, rules, constraints).all { it.satisfied }) {
                val energy = computeEnergy(x, q)
                if (energy < bestEnergy) { best = x; bestEnergy = energy }
            }
        }
        val chosen = best ?: List(rules.size) { 0 }
        val checks = verifyConstraints(chosen, rules, constraints)
        val active = rules.filterIndexed { i, _ -> chosen[i] == 1 }
        val inactive = rules.filterIndexed { i, _ -> chosen[i] == 0 }
        val maxCost = constraints.filterIsInstance<Constraint.MaxCost>().firstOrNull()?.budget
        val totalCost = active.sumOf { it.cost }
        val hash = sha256("config=$chosen|energy=$bestEnergy|seed=${config.seed}|evaluated=$evaluated")
        return QuboSolution(chosen, active, inactive, totalCost, active.sumOf { it.riskReduction }, active.sumOf { it.businessValue }, bestEnergy, active.size, if (maxCost == null || maxCost == 0.0) 0.0 else totalCost / maxCost, checks.all { it.satisfied }, checks, config.seed, evaluated, hash, evaluated)
    }

    fun counterfactual(rules: List<PolicyRule>, originalConstraints: List<Constraint>, alteredConstraints: List<Constraint>, config: EngineConfig): CounterfactualResult {
        val a = solve(rules, originalConstraints, config); val b = solve(rules, alteredConstraints, config)
        val changed = rules.indices.filter { a.configuration[it] != b.configuration[it] }.map { "${rules[it].name}: ${if (b.configuration[it] == 1) "ACTIVATED" else "DEACTIVATED"}" }
        return CounterfactualResult(a, b, changed.isNotEmpty(), b.totalCost - a.totalCost, b.totalRiskReduction - a.totalRiskReduction, b.totalBusinessValue - a.totalBusinessValue, changed)
    }

    fun quboToIsing(q: List<List<Double>>): IsingModel {
        val n = q.size; val j = List(n) { MutableList(n) { 0.0 } }; val h = MutableList(n) { 0.0 }; var offset = 0.0
        for (i in 0 until n) for (k in i + 1 until n) { val v = (q[i][k] + q[k][i]) / 4.0; j[i][k] = v; j[k][i] = v }
        for (i in 0 until n) { h[i] = q[i][i] / 2.0 + (0 until n).filter { it != i }.sumOf { k -> (q[i][k] + q[k][i]) / 4.0 }; offset += q[i][i] / 4.0 }
        for (i in 0 until n) for (k in i + 1 until n) offset += (q[i][k] + q[k][i]) / 4.0
        return IsingModel(j.map { it.toList() }, h, offset)
    }

    private fun sha256(value: String): String = MessageDigest.getInstance("SHA-256").digest(value.toByteArray()).joinToString("") { "%02x".format(it) }
}
