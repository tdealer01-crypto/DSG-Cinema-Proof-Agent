package com.example.data.qubo

data class PolicyRule(val id: Int, val name: String, val cost: Double, val riskReduction: Double, val businessValue: Double, val category: String, val description: String = "")

sealed class Constraint {
    abstract val description: String
    data class Implication(val ifRule: Int, val thenRule: Int, override val description: String = "") : Constraint()
    data class Equivalence(val rules: List<Int>, override val description: String = "") : Constraint()
    data class MinActive(val minimum: Int, override val description: String = "") : Constraint()
    data class MaxCost(val budget: Double, override val description: String = "") : Constraint()
    data class MutualExclusion(val rules: List<Int>, override val description: String = "") : Constraint()
    data class AtLeastOneOf(val rules: List<Int>, override val description: String = "") : Constraint()
}

data class EngineConfig(val seed: Long = 42L, val maxIterations: Int = 5000, val initialTemperature: Double = 100.0, val minTemperature: Double = 0.001, val coolingRate: Double = 0.995, val penaltyWeight: Double = 1000.0, val snapshotInterval: Int = 100)
data class EvolutionEvent(val sequence: Int, val timestamp: String, val site: Int, val proposed: String, val accepted: Boolean, val reason: String, val energy: Double, val deltaEnergy: Double, val temperature: Double, val state: List<Int>, val prevHash: String, val hash: String)
data class ConstraintResult(val constraint: Constraint, val satisfied: Boolean, val detail: String)
data class QuboSolution(val configuration: List<Int>, val activeRules: List<PolicyRule>, val inactiveRules: List<PolicyRule>, val totalCost: Double, val totalRiskReduction: Double, val totalBusinessValue: Double, val quboEnergy: Double, val activeCount: Int, val budgetUtilization: Double, val allConstraintsSatisfied: Boolean, val constraintResults: List<ConstraintResult>, val seed: Long, val iterations: Int, val solutionHash: String, val chainLength: Int)
data class CounterfactualResult(val originalSolution: QuboSolution, val alteredSolution: QuboSolution, val diverges: Boolean, val costDelta: Double, val riskDelta: Double, val valueDelta: Double, val rulesChanged: List<String>)
data class IsingModel(val J: List<List<Double>>, val h: List<Double>, val offset: Double)
