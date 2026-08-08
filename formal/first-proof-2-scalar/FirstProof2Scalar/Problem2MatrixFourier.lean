import Mathlib.Analysis.Fourier.ZMod
import Mathlib.LinearAlgebra.Matrix.Defs

namespace Problem2MatrixFourier

open AddChar Matrix

variable {N r c : ℕ} [NeZero N]

/-- Frobenius-style entrywise dot-product homomorphism on a finite matrix quotient. -/
def matrixDotHom (K : Matrix (Fin r) (Fin c) (ZMod N)) :
    Matrix (Fin r) (Fin c) (ZMod N) →+ ZMod N where
  toFun X := ∑ i, ∑ j, K i j * X i j
  map_zero' := by simp
  map_add' X Y := by
    simp [mul_add, Finset.sum_add_distrib]

/-- Additive character associated to a matrix frequency `K`. -/
noncomputable def matrixChar (K : Matrix (Fin r) (Fin c) (ZMod N)) :
    AddChar (Matrix (Fin r) (Fin c) (ZMod N)) ℂ :=
  (ZMod.stdAddChar (N := N)).compAddMonoidHom (matrixDotHom K)

lemma matrixChar_ne_one_of_ne_zero
    {K : Matrix (Fin r) (Fin c) (ZMod N)} (hK : K ≠ 0) :
    matrixChar K ≠ 1 := by
  rw [AddChar.ne_one_iff]
  have hentry : ∃ i j, K i j ≠ 0 := by
    by_contra h
    push_neg at h
    apply hK
    ext i j
    exact h i j
  rcases hentry with ⟨i, j, hij⟩
  let E : Matrix (Fin r) (Fin c) (ZMod N) :=
    fun a b => if a = i ∧ b = j then 1 else 0
  refine ⟨E, ?_⟩
  have hdot : matrixDotHom K E = K i j := by
    simp [matrixDotHom, E]
  rw [matrixChar, AddChar.compAddMonoidHom_apply, hdot]
  intro hchar
  have hkzero : K i j = 0 :=
    ((ZMod.isPrimitive_stdAddChar N).zmod_char_eq_one_iff N (K i j)).mp hchar
  exact hij hkzero

/--
Orthogonality on a finite matrix conductor quotient.

The sum of the matrix-frequency additive character over the full matrix additive
space equals the matrix-space cardinality at zero frequency and vanishes at
every nonzero frequency.
-/
theorem matrix_character_sum (K : Matrix (Fin r) (Fin c) (ZMod N)) :
    ∑ X : Matrix (Fin r) (Fin c) (ZMod N), matrixChar K X =
      if K = 0 then
        (Fintype.card (Matrix (Fin r) (Fin c) (ZMod N)) : ℂ)
      else 0 := by
  split_ifs with hK
  · subst K
    apply AddChar.sum_eq_card_of_eq_one
    ext X
    simp [matrixChar, matrixDotHom]
  · exact AddChar.sum_eq_zero_of_ne_one (matrixChar_ne_one_of_ne_zero hK)

/-- Every nonzero matrix frequency has zero total character sum. -/
theorem matrix_character_sum_eq_zero_of_ne_zero
    (K : Matrix (Fin r) (Fin c) (ZMod N)) (hK : K ≠ 0) :
    ∑ X : Matrix (Fin r) (Fin c) (ZMod N), matrixChar K X = 0 := by
  rw [matrix_character_sum]
  simp [hK]

end Problem2MatrixFourier
