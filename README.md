# Budget for dansk ægtepar

Mini-projektet bruger Streamlit til at estimere husstandens månedlige nettoindtægter under danske skatteregler.

## Opsætning med Miniforge (Conda)
1. Sørg for at have [Miniforge](https://github.com/conda-forge/miniforge) installeret.
2. Opret miljøet:
   ```bash
   conda env create -f environment.yml
   ```
3. Aktivér miljøet:
   ```bash
   conda activate boligbudget
   ```
4. Start appen fra miljøet:
   ```bash
   streamlit run app.py
   ```

## Fradrag og pendlerlogik
- Fradragssektionen i appen forklarer nu hvert felt med hjælpetekst og en kort guide i ekspanderen, så det er tydeligere hvilke beløb der hører til hvor.
- Koerselsfradrag beregnes automatisk ud fra indtastet afstand mellem hjem og arbejde samt antallet af pendlerdage. Modellen bruger de gældende satser (2,23 DKK pr. km i zonen 24-120 km og 1,12 DKK over 120 km), og der kan tilføjes manuelle justeringer, hvis virkeligheden afviger.

## Boligkøb, bil og faste udgifter
- Boligmodulet estimerer nu både månedlige udgifter og den årlige renteudgift, som automatisk fordeles mellem personerne og bruges som fradrag (med mulighed for manuel justering).
- Rente-felterne i fradragssektionen bliver forhåndsudfyldt med hver persons del af den beregnede bolig-rente, så modellen selv skriver ind i fradraget.
- Personfradrag deles automatisk mellem ægtefæller: hvis den ene ikke udnytter hele fradraget, flyttes resten til partneren og vises i UI'et.
- Bilmodulet giver et samlet overblik over billån, brændstof, forsikring og service og kan indgå direkte i de faste udgifter.
- Modulet for faste månedlige udgifter gør det let at liste de største poster (inkl. beregnet boligydelse og bil) og giver et hurtigt overblik over rådighedsbeløbet efter faste udgifter.

## Validering og videre arbejde
- Sammenlign resultaterne mod faktiske SKAT-beregninger for en kendt husstand. Justér topskattegrænse, kommuneskat eller fradragssatser i sidepanelet, eller opdater defaultværdierne i `tax_engine.py`, indtil modellen matcher.
- Udvid børnepengelogikken ved at angive fødselsdatoer og automatisk flytte børn mellem aldersgrupper gennem året.
- Tilføj ekstra blokke til pensionsindbetalinger eller opsparingsmål, fx frivillig pensionsopsparing og månedlige investeringer, så nettoindtægten kan fordeles videre.
