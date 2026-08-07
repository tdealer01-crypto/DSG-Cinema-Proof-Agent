package com.example.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.data.mcp.McpDispatchResult
import com.example.data.mcp.McpEndpointType
import com.example.data.mcp.McpGatewayEngine
import com.example.data.qubo.EngineConfig
import com.example.data.qubo.QuboPolicyEngine
import com.example.data.qubo.QuboSolution
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class TaskViewModel : ViewModel() {
    private val rules = QuboPolicyEngine.FINTECH_RULES
    private val constraints = QuboPolicyEngine.FINTECH_CONSTRAINTS

    private val _solution = MutableStateFlow(
        QuboPolicyEngine.solve(rules, constraints, EngineConfig(seed = 42L, maxIterations = 5000))
    )
    val solution: StateFlow<QuboSolution> = _solution.asStateFlow()

    private val _backendResult = MutableStateFlow<McpDispatchResult?>(null)
    val backendResult: StateFlow<McpDispatchResult?> = _backendResult.asStateFlow()

    private val _isVerifying = MutableStateFlow(false)
    val isVerifying: StateFlow<Boolean> = _isVerifying.asStateFlow()

    fun recomputeCandidate() {
        _solution.value = QuboPolicyEngine.solve(
            rules,
            constraints,
            EngineConfig(seed = 42L, maxIterations = 5000)
        )
        _backendResult.value = null
    }

    fun verifyWithBackend() {
        if (_isVerifying.value) return
        viewModelScope.launch {
            _isVerifying.value = true
            try {
                _backendResult.value = McpGatewayEngine.dispatchToEndpoint(
                    endpoint = McpEndpointType.DSG_BACKEND,
                    presetName = "FINTECH",
                    solution = _solution.value,
                    rules = rules,
                    constraints = constraints
                )
            } finally {
                _isVerifying.value = false
            }
        }
    }
}
