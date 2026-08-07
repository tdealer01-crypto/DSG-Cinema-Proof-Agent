package com.example

import com.example.data.qubo.EngineConfig
import com.example.data.qubo.QuboPolicyEngine
import org.junit.Assert.*
import org.junit.Test

class ExampleUnitTest {
    @Test fun criminalLawPresetIsDeterministicAndValid() {
        val a = QuboPolicyEngine.solve(QuboPolicyEngine.CRIMINAL_LAW_RULES, QuboPolicyEngine.CRIMINAL_LAW_CONSTRAINTS, EngineConfig(seed = 42L, maxIterations = 5000))
        val b = QuboPolicyEngine.solve(QuboPolicyEngine.CRIMINAL_LAW_RULES, QuboPolicyEngine.CRIMINAL_LAW_CONSTRAINTS, EngineConfig(seed = 42L, maxIterations = 5000))
        assertTrue(a.allConstraintsSatisfied)
        assertTrue(a.activeCount >= 2)
        assertTrue(a.totalCost <= 1000.0)
        assertTrue(a.iterations > 0)
        assertEquals(a.configuration, b.configuration)
        assertEquals(a.solutionHash, b.solutionHash)
        assertEquals(a.quboEnergy, b.quboEnergy, 1e-9)
    }

    @Test fun euPresetSatisfiesConstraints() {
        val s = QuboPolicyEngine.solve(QuboPolicyEngine.EU_GDPR_AI_ACT_RULES, QuboPolicyEngine.EU_GDPR_AI_ACT_CONSTRAINTS, EngineConfig())
        assertTrue(s.allConstraintsSatisfied)
        assertTrue(s.activeCount >= 3)
        assertTrue(s.totalCost <= 1500.0)
    }

    @Test fun thaiPdpaPresetSatisfiesConstraints() {
        val s = QuboPolicyEngine.solve(QuboPolicyEngine.THAI_PDPA_RULES, QuboPolicyEngine.THAI_PDPA_CONSTRAINTS, EngineConfig())
        assertTrue(s.allConstraintsSatisfied)
        assertTrue(s.activeCount >= 2)
        assertTrue(s.totalCost <= 800.0)
    }

    @Test fun fintechPresetSatisfiesConstraints() {
        val s = QuboPolicyEngine.solve(QuboPolicyEngine.FINTECH_RULES, QuboPolicyEngine.FINTECH_CONSTRAINTS, EngineConfig())
        assertTrue(s.allConstraintsSatisfied)
        assertTrue(s.activeCount >= 4)
        assertTrue(s.totalCost <= 1500.0)
    }

    @Test fun isingTransformationHasExpectedDimensions() {
        val q = QuboPolicyEngine.buildQUBOMatrix(QuboPolicyEngine.THAI_PDPA_RULES, QuboPolicyEngine.THAI_PDPA_CONSTRAINTS, 1000.0)
        val ising = QuboPolicyEngine.quboToIsing(q)
        assertEquals(QuboPolicyEngine.THAI_PDPA_RULES.size, ising.J.size)
        assertEquals(QuboPolicyEngine.THAI_PDPA_RULES.size, ising.h.size)
    }
}
