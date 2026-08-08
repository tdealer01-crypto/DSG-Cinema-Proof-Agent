import Mathlib

namespace Problem2Logical

universe uBig uPsi uSmall uW uQ uV uS

/--
Abstract proof-assistant model of the quantifier/dependency structure of
First Proof #2.

The predicates below intentionally do not pretend to define p-adic
representation theory.  Instead, each deep mathematical stage is supplied
as an explicit theorem hypothesis.  Lean checks only that these hypotheses
compose with the required quantifier order: one larger-group vector `w` is
chosen before the universally quantified smaller representation `pi`.
-/
theorem reference_dependency_logical_closure
    {BigRep : Type uBig}
    {Psi : Type uPsi}
    {SmallRep : Type uSmall}
    {W : Type uW}
    {Q : Type uQ}
    {V : Type uV}
    {S : Type uS}
    (Pi : BigRep)
    (psi : Psi)
    (UniversalW : W → BigRep → Psi → Prop)
    (Conductor : SmallRep → Q → Prop)
    (GJReady : W → SmallRep → Q → Prop)
    (MellinReady : W → SmallRep → Q → Prop)
    (K1Ready : W → SmallRep → Q → Prop)
    (NewvectorReady : W → SmallRep → Q → V → Prop)
    (IntegralFiniteNonzero : W → SmallRep → Q → V → S → Prop)
    (hKirillovExtension : ∃ w, UniversalW w Pi psi)
    (hConductor : ∀ pi, ∃ q, Conductor pi q)
    (hGodementJacquet :
      ∀ w pi q,
        UniversalW w Pi psi → Conductor pi q → GJReady w pi q)
    (hMellinSupport :
      ∀ w pi q,
        GJReady w pi q → MellinReady w pi q)
    (hFourierToK1 :
      ∀ w pi q,
        MellinReady w pi q → K1Ready w pi q)
    (hNormalizedNewvector :
      ∀ w pi q,
        K1Ready w pi q → ∃ v, NewvectorReady w pi q v)
    (hEpsilonNonvanishing :
      ∀ w pi q v,
        NewvectorReady w pi q v →
        ∀ s, IntegralFiniteNonzero w pi q v s) :
    ∃ w,
      UniversalW w Pi psi ∧
      ∀ pi,
        ∃ q v,
          Conductor pi q ∧
          NewvectorReady w pi q v ∧
          ∀ s, IntegralFiniteNonzero w pi q v s := by
  rcases hKirillovExtension with ⟨w, hw⟩
  refine ⟨w, hw, ?_⟩
  intro pi
  rcases hConductor pi with ⟨q, hq⟩
  have hgj : GJReady w pi q := hGodementJacquet w pi q hw hq
  have hmellin : MellinReady w pi q := hMellinSupport w pi q hgj
  have hk1 : K1Ready w pi q := hFourierToK1 w pi q hmellin
  rcases hNormalizedNewvector w pi q hk1 with ⟨v, hv⟩
  refine ⟨q, v, hq, hv, ?_⟩
  exact hEpsilonNonvanishing w pi q v hv

/--
The forbidden weaker quantifier shape is documented as a separate type:
`∀ pi, ∃ w, ...` permits the larger-group vector to change with `pi`.
It is intentionally not used to derive the target theorem above.
-/
def WeakerPiDependentShape
    {SmallRep : Type uSmall}
    {W : Type uW}
    (WorksFor : W → SmallRep → Prop) : Prop :=
  ∀ pi, ∃ w, WorksFor w pi

/-- The required universal shape fixes `w` outside the `∀ pi` quantifier. -/
def RequiredUniversalShape
    {SmallRep : Type uSmall}
    {W : Type uW}
    (WorksFor : W → SmallRep → Prop) : Prop :=
  ∃ w, ∀ pi, WorksFor w pi

end Problem2Logical
