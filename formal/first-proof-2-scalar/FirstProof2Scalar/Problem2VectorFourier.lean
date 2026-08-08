import Mathlib.Analysis.Fourier.ZMod

namespace Problem2VectorFourier

open AddChar

variable {N d : ℕ} [NeZero N]

/-- Dot-product homomorphism on a finite conductor quotient coordinate space. -/
def dotHom (k : Fin d → ZMod N) : (Fin d → ZMod N) →+ ZMod N where
  toFun x := ∑ i, k i * x i
  map_zero' := by simp
  map_add' x y := by
    simp [mul_add, Finset.sum_add_distrib]

/-- Additive character associated to a frequency vector `k`. -/
noncomputable def vectorChar (k : Fin d → ZMod N) : AddChar (Fin d → ZMod N) ℂ :=
  (ZMod.stdAddChar (N := N)).compAddMonoidHom (dotHom k)

lemma vectorChar_ne_one_of_ne_zero {k : Fin d → ZMod N} (hk : k ≠ 0) :
    vectorChar k ≠ 1 := by
  rw [AddChar.ne_one_iff]
  have hcoord : ∃ i, k i ≠ 0 := by
    by_contra h
    push_neg at h
    apply hk
    funext i
    exact h i
  rcases hcoord with ⟨i, hi⟩
  let e : Fin d → ZMod N := fun j => if j = i then 1 else 0
  refine ⟨e, ?_⟩
  have hdot : dotHom k e = k i := by
    simp [dotHom, e]
  rw [vectorChar, AddChar.compAddMonoidHom_apply, hdot]
  intro hchar
  have hkzero : k i = 0 :=
    ((ZMod.isPrimitive_stdAddChar N).zmod_char_eq_one_iff N (k i)).mp hchar
  exact hi hkzero

/--
Orthogonality on a finite coordinate conductor quotient.

For frequency vector `k`, the sum of the associated additive character over all
vectors is the cardinality of the coordinate space at zero frequency and zero
at every nonzero frequency.
-/
theorem vector_character_sum (k : Fin d → ZMod N) :
    ∑ x : Fin d → ZMod N, vectorChar k x =
      if k = 0 then (Fintype.card (Fin d → ZMod N) : ℂ) else 0 := by
  split_ifs with hk
  · subst k
    apply AddChar.sum_eq_card_of_eq_one
    ext x
    simp [vectorChar, dotHom]
  · exact AddChar.sum_eq_zero_of_ne_one (vectorChar_ne_one_of_ne_zero hk)

/-- Nonzero vector frequencies have zero total character sum. -/
theorem vector_character_sum_eq_zero_of_ne_zero
    (k : Fin d → ZMod N) (hk : k ≠ 0) :
    ∑ x : Fin d → ZMod N, vectorChar k x = 0 := by
  rw [vector_character_sum]
  simp [hk]

end Problem2VectorFourier
