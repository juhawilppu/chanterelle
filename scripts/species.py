"""Per-species habitat profiles for the Karkkila mushroom maps.

Everything that differs between the mushrooms lives here: which stands are
habitat at all, how each forestry attribute scores, how many points each
factor is worth, and what the map calls things. `build_map.py` is a single
scoring engine driven by these profiles, so adding a species is a matter of
writing one more profile rather than forking the pipeline.

The two profiles are deliberately near-opposites in places -- kantarelli
wants dry, well-drained, light-flooded mineral soil near eskers, while
suppilovahvero wants damp, shady, moss-floored spruce forest and is happy on
peat -- which is exactly why the two maps are worth having side by side.

Point tables are calibrated against real laji.fi sightings; see
`scripts/calibrate.py` and the per-table comments.
"""

from dataclasses import dataclass, field

# --- shared code tables (metsätietostandardi), species-independent ---------

FERTILITY_LABELS = {
    "1": "Lehto", "2": "Lehtomainen kangas (OMT)", "3": "Tuore kangas (MT)",
    "4": "Kuivahko kangas (VT)", "5": "Kuiva kangas (CT)", "6": "Karukkokangas",
    "7": "Kalliomaa ja hietikko", "8": "Lakimetsä ja tunturi",
}

DEVELOPMENT_LABELS = {
    "02": "Nuori kasvatusmetsikkö", "03": "Varttunut kasvatusmetsikkö",
    "04": "Uudistuskypsä metsikkö", "05": "Suojuspuumetsikkö",
    "ER": "Eri-ikäisrakenteinen", "S0": "Siemenpuumetsikkö",
    "Y1": "Ylispuustoinen taimikko", "T2": "Taimikko",
}

SOIL_LABELS = {
    "10": "Karkea kangasmaa", "11": "Karkea moreeni", "12": "Karkea lajittunut maalaji",
    "20": "Hienojakoinen kangasmaa", "21": "Hienoainesmoreeni", "22": "Hienojakoinen lajittunut maalaji",
    "23": "Silttipitoinen maalaji", "24": "Savimaa",
    "30": "Kivinen karkea kangasmaa", "31": "Kivinen karkea moreeni",
    "32": "Kivinen karkea lajittunut maalaji", "40": "Kivinen hienojakoinen kangasmaa",
    "50": "Kallio/kivikko", "60": "Turvemaa", "61": "Saraturve", "62": "Rahkaturve",
    "70": "Multamaa", "80": "Liejumaa",
}

# Shown in brackets after the soil type ("Karkea kangasmaa (ojittamaton)"),
# so the "kangas"/"suo" half of each official name is left off as redundant.
DRAINAGE_LABELS = {
    "1": "ojittamaton", "2": "soistunut", "3": "ojitettu",
    "6": "ojittamaton suo", "7": "ojikko", "8": "muuttuma", "9": "turvekangas",
}

TREESPECIES_LABELS = {
    "1": "Mänty", "2": "Kuusi", "3": "Rauduskoivu", "4": "Hieskoivu",
    "5": "Haapa", "6": "Harmaaleppä", "7": "Tervaleppä",
    "29": "Lehtipuu", "30": "Havupuu",
}

# Gini-Simpson bands. A description of the stand itself, not of how good that
# stand is for a given mushroom, so both species share it.
MIXTURE_BANDS = [(0.55, "Vahva sekametsä"), (0.3, "Jonkin verran sekapuustoa")]
MIXTURE_FALLBACK = "Lähes yksipuulajinen"

EXCLUDED_DEVELOPMENT = {"A0", "T1"}  # Aukea, Taimikko alle 1.3 m -- no forest floor yet
MID_THRESHOLD = 0.3  # ratio below which a factor's badge turns red, for every species

# Share of the raw point total a stand keeps when one factor is at rock
# bottom. 1.0 would be a pure sum (full compensation between factors);
# lower values make the worst factor bite harder (Liebig's law of the minimum).
LIMITING_FLOOR = 0.7

ESKER_BUFFER_M = 150


@dataclass(frozen=True)
class LightProfile:
    """Canopy density response, as a piecewise-linear curve over stems/ha.

    Both species care about how much light reaches the floor; they just want
    opposite ends of it. The curve is a band rather than a slope either way,
    because a nearly treeless stand has no living mycorrhizal host no matter
    how the species feels about shade.
    """

    stemcount_knots: list[float]
    suitability_knots: list[float]
    row_label: str
    label_good: str
    label_mid: str   # off the preferred band, but not badly
    label_poor: str  # far off it, in the same direction as label_mid
    # Below this stem density the stand is simply too empty to host anything,
    # which is a different failure from "wrong kind of light" and has to be
    # said differently -- otherwise a nearly treeless stand reads as "dense".
    sparse_stems: float
    label_sparse: str


@dataclass(frozen=True)
class SpeciesProfile:
    slug: str
    map_key: str         # short property key this species' scores ship under
    name: str            # Finnish name, as shown in the UI
    latin: str
    laji_target: str     # laji.fi search target (scientific name)
    intro: str           # one-line habitat summary for the legend

    fertility_points: dict[str, float]
    development_points: dict[str, float]
    soil_points: dict[str, float]
    soil_default: float
    drainage_multiplier: dict[str, float]
    drainage_default: float
    species_weight: dict[str, float]
    species_weight_default: float

    excluded_subgroup: set[str]
    excluded_fertility: set[str]

    mixture_points: float
    species_points: float
    light_points: float
    light: LightProfile

    green_thresholds: dict[str, float]
    esker_points: float = 0.0
    esker_row_labels: tuple[str, str] = ("", "")
    default_fertility_points: float = 6.0
    default_development_points: float = 8.0

    # factor -> point budget, so the "x/100" on the map stays honest
    @property
    def factor_points(self) -> dict[str, float]:
        return {
            "fertility": max(self.fertility_points.values()),
            "development": max(self.development_points.values()),
            "species": self.species_points,
            "mixture": self.mixture_points,
            "light": self.light_points,
            "soil": max(self.soil_points.values()),
        }

    @property
    def max_raw_score(self) -> float:
        return sum(self.factor_points.values()) + self.esker_points

    @property
    def uses_esker(self) -> bool:
        return self.esker_points > 0


KANTARELLI = SpeciesProfile(
    slug="kantarelli",
    map_key="k",
    name="Kantarelli",
    latin="Cantharellus cibarius",
    laji_target="Cantharellus cibarius",
    intro="Kuivahko, valoisa kangasmetsä hyvin vettä läpäisevällä maaperällä.",

    fertility_points={
        # Weights calibrated against real Cantharellus cibarius sightings from
        # laji.fi (see scripts/calibrate.py): compared against Karkkila's own
        # stand population, MT-fertility sightings landed almost exactly at
        # prevalence (well calibrated already), VT was notably under-weighted
        # here relative to how often real sightings land there, and OMT was
        # somewhat over-weighted relative to its (high) prevalence.
        "1": 17,  # Lehto - lush but often too dense/herby
        "2": 19,  # Lehtomainen kangas (OMT) - good, but not as dominant as raw prevalence suggests
        "3": 25,  # Tuore kangas (MT) - prime, matches real sightings almost exactly
        "4": 18,  # Kuivahko kangas (VT) - real sightings favor this more than expected
        "5": 10,  # Kuiva kangas (CT)
        "6": 3,   # Karukkokangas
        "7": 0,   # Kalliomaa ja hietikko
        "8": 0,   # Lakimetsä ja tunturi
    },
    development_points={
        # Calibrated against laji.fi sightings: the oldest, regeneration-ready
        # stands (04) were 4x over-represented at real sighting locations
        # relative to their prevalence -- the strongest single signal in the
        # calibration -- while 03 (previously tied for best) was slightly
        # under-represented. 04 is now the top category instead of 03.
        "02": 10,  # Nuori kasvatusmetsikkö - real sightings avoid this
        "03": 20,  # Varttunut kasvatusmetsikkö - good, but not the top anymore
        "04": 25,  # Uudistuskypsä metsikkö - real sightings favor this most
        "05": 15,  # Suojuspuumetsikkö
        "ER": 18,  # Eri-ikäisrakenteinen
        "S0": 5,   # Siemenpuumetsikkö - too open
        "Y1": 5,   # Ylispuustoinen taimikko
        "T2": 2,   # Taimikko yli 1.3 m - too young
    },
    soil_points={  # coarse/well-drained mineral soils score best
        "10": 15, "11": 15, "12": 15, "30": 14, "31": 14, "32": 14,
        "20": 9, "21": 9, "22": 9, "23": 8, "24": 7, "40": 8,
        "50": 8,
        "70": 7,  # Multamaa - organic-rich, holds moisture, middling for kantarelli
    },
    soil_default=7,
    drainage_multiplier={
        "1": 1.0,  # Ojittamaton kangas - natural
        "3": 0.8,  # Ojitettu kangas - ditched, altered hydrology
        "2": 0.5,  # Soistunut kangas - paludified
    },
    drainage_default=0.2,  # everything else here is peatland hydrology
    species_weight={
        # Calibrated against real laji.fi sightings (scripts/calibrate.py):
        # Mänty-dominant stands were 2x over-represented at real sighting
        # locations relative to their prevalence -- pine is a much stronger
        # chanterelle host here than a low weight would suggest, raised sharply.
        # Lehtipuu (unspecified broadleaf) was previously raised on the
        # assumption that unresolved broadleaf is mostly birch, but real
        # sightings are 10x LESS common there than prevalence would predict --
        # that assumption doesn't hold up against the data, so it's lowered
        # back down, below its original default even.
        "2": 1.0,   # Kuusi / Norway spruce - main host, matches real sightings closely
        "1": 0.75,  # Mänty / Scots pine - real sightings show this is a strong host too
        "3": 0.6,   # Rauduskoivu / silver birch (too few sightings to recalibrate)
        "4": 0.6,   # Hieskoivu / downy birch (too few sightings to recalibrate)
        "30": 0.4,  # Havupuu / unspecified conifer - no sighting data to calibrate against
        "29": 0.2,  # Lehtipuu / unspecified broadleaf - real sightings clearly avoid this
    },
    species_weight_default=0.1,
    excluded_subgroup={"2", "3", "4", "5"},  # Korpi, Räme, Neva, Letto - mire types
    excluded_fertility={"7", "8"},
    # the mixture half outweighs raw host quality, per specific request to
    # emphasize genuinely mixed forest over a monoculture of the "best" species
    mixture_points=15,
    species_points=10,
    light_points=10,
    light=LightProfile(
        # "valoisuus": repeatedly cited in foraging sources ("avoid dense dark
        # forest"), but not captured by development class alone -- a stand can
        # have high basal area from a few big old trees (open) or many small
        # crowded ones (dark) at the same age. Calibrated against real laji.fi
        # sightings: 74% fall in 300-800 stems/ha (vs 44% of background),
        # dropping off sharply above 800 and effectively absent below 300.
        stemcount_knots=[0, 100, 400, 800, 2000],
        suitability_knots=[0.25, 0.25, 1.0, 1.0, 0.0],
        row_label="Valoisuus",
        label_good="Avoin, valoisa",
        label_mid="Melko tiheä",
        label_poor="Tiheä, vähän valoa",
        sparse_stems=400,
        label_sparse="Hyvin harva puusto",
    ),
    green_thresholds={
        "fertility": 0.65,
        "development": 0.65,
        "species": 0.65,
        "mixture": 0.55,   # Gini-Simpson tops out near 0.67 in practice
        "light": 0.75,     # roughly 325-1100 stems/ha, the empirically enriched band
        "soil": 0.65,
    },
    esker_points=10,
    esker_row_labels=("Lähellä harju-/reunamuodostumaa", "Ei lähellä harjumuodostumaa"),
)


SUPPILOVAHVERO = SpeciesProfile(
    slug="suppilovahvero",
    map_key="s",
    name="Suppilovahvero",
    latin="Craterellus tubaeformis",
    laji_target="Craterellus tubaeformis",
    intro="Varttunut kuusivaltainen kangasmetsä; sietää kosteampaa ja karumpaa kasvupaikkaa kuin kantarelli.",

    fertility_points={
        # Calibrated against 710 real Craterellus tubaeformis sightings from
        # laji.fi (scripts/calibrate.py). The folk description -- damp, rich,
        # mossy ground -- turns out not to survive contact with the data: MT
        # sits exactly at prevalence, OMT is clearly UNDER-represented (0.6x),
        # and the drier VT is over-represented (1.7x). The dry end (CT,
        # karukko) is enriched too, but on so few sightings that it only earns
        # a mild score rather than a top one.
        "1": 12,  # Lehto - herb layer crowds out the moss carpet
        "2": 15,  # Lehtomainen kangas (OMT) - under-represented relative to how common it is
        "3": 20,  # Tuore kangas (MT) - over half of all sightings
        "4": 17,  # Kuivahko kangas (VT) - genuinely favoured, not merely tolerated
        "5": 10,  # Kuiva kangas (CT) - enriched, but on thin evidence
        "6": 5,   # Karukkokangas
        "7": 0, "8": 0,
    },
    default_fertility_points=5,
    development_points={
        # The single strongest signal in the calibration, and the same one the
        # kantarelli model found: regeneration-ready stands (04) carry 45% of
        # sightings against 10% of the available forest, a 4.4x enrichment,
        # while young stands (02) and thickets are 5x AVOIDED. Whatever
        # suppilovahvero gets from a dense young spruce stand, it is not
        # fruiting bodies -- so this profile gives development class the
        # largest point budget of any factor.
        "02": 8,   # Nuori kasvatusmetsikkö - 0.2x, strongly avoided
        "03": 17,  # Varttunut kasvatusmetsikkö - common, but slightly under-represented
        "04": 25,  # Uudistuskypsä metsikkö - by far the best predictor
        "05": 12,  # Suojuspuumetsikkö
        "ER": 16,  # Eri-ikäisrakenteinen - has the old cohort that matters
        "S0": 5,   # Siemenpuumetsikkö
        "Y1": 5,   # Ylispuustoinen taimikko
        "T2": 4,   # Taimikko yli 1.3 m
    },
    default_development_points=6,
    soil_points={
        # Another prior the data overturned: fine-textured, moisture-holding
        # soils were expected to lead and instead came in at 0.6x, while plain
        # coarse mineral soil (1.4x) and stony ground (2.2x) are where the
        # sightings actually are. Rock -- which the kantarelli model treats as
        # a dead end -- is enriched 4.8x here, which fits the mossy,
        # boulder-strewn spruce forest this species is picked in. Peat sits
        # near prevalence, so it is neither the point nor a disqualifier.
        "10": 15, "11": 15, "12": 14, "30": 15, "31": 14, "32": 13,
        "50": 12,  # Kallio/kivikko - genuinely productive, unlike for kantarelli
        "60": 12, "61": 11, "62": 10, "70": 10, "80": 9,
        "20": 10, "21": 9, "22": 10, "23": 9, "24": 8, "40": 11,
    },
    soil_default=11,
    drainage_multiplier={
        # Here the damp-ground reputation does hold up: paludified kangas
        # (2.0x) and undrained mire (1.8x) are both enriched, and ditched
        # ground is the only state that is genuinely under-represented. So
        # unlike the kantarelli model, wetness is not penalised -- it is just
        # not the strong positive the fertility and soil tables were expected
        # to show.
        "1": 1.0,   # Ojittamaton kangas
        "2": 1.0,   # Soistunut kangas - paludified, 2x enriched
        "3": 0.85,  # Ojitettu kangas - the one state sightings avoid
        "6": 0.85,  # Ojittamaton suo
        "7": 0.9,   # Ojikko
        "8": 0.85,  # Muuttuma
        "9": 0.85,  # Turvekangas
    },
    drainage_default=0.85,
    species_weight={
        # Spruce dominates the sightings (66%, and a mean spruce proportion of
        # 0.49 at sighting locations), which is the one part of the textbook
        # description the data backs without reservation. Pine still comes out
        # over-represented against its own prevalence, the same way it did for
        # kantarelli, so it is scored as a real if secondary host rather than
        # the near-miss the literature implies.
        "2": 1.0,   # Kuusi - the host that matters
        "1": 0.6,   # Mänty - over-represented against prevalence
        "30": 0.8,  # Havupuu / unspecified conifer - mostly spruce here
        "3": 0.4,   # Rauduskoivu
        "4": 0.4,   # Hieskoivu
        "29": 0.15, # Lehtipuu / unspecified broadleaf - all but absent from sightings
    },
    species_weight_default=0.15,
    # Korpi (spruce mire) stays in, unlike in the kantarelli model: it is
    # forest with a spruce canopy and the drainage evidence above says damp
    # ground is fine. Only the treeless and pine-bog mire types go.
    excluded_subgroup={"3", "4", "5"},  # Räme, Neva, Letto
    excluded_fertility={"7", "8"},
    # a spruce monoculture is a perfectly good suppilovahvero forest, so
    # mixedness stays a mild positive at most -- the weight that the kantarelli
    # model puts on sekametsä goes to development class and host species here
    mixture_points=5,
    species_points=20,
    light_points=15,
    light=LightProfile(
        # Calibrated off stem density at sighting locations: 300-600 stems/ha
        # is enriched 1.9x and 600-900 sits at prevalence, with a steady
        # falloff above (0.4x at 1400-2200, 0.2x beyond). So this species does
        # NOT want the dark dense thicket it is usually described as haunting;
        # it wants roughly the same half-open canopy kantarelli does, just
        # holding on somewhat better into denser forest.
        stemcount_knots=[0, 150, 350, 900, 1600, 3000],
        suitability_knots=[0.1, 0.25, 1.0, 1.0, 0.45, 0.2],
        row_label="Valoisuus",
        label_good="Avoin, valoisa",
        label_mid="Melko tiheä",
        label_poor="Tiheä, vähän valoa",
        sparse_stems=350,
        label_sparse="Hyvin harva puusto",
    ),
    green_thresholds={
        "fertility": 0.7,   # MT, VT and OMT
        # Only uudistuskypsä (04) counts as green here. That is a hard line --
        # it puts a yellow dot on the varttunut kasvatusmetsikkö that most of
        # Karkkila consists of -- but 04 is the category real sightings pick
        # out 4.4x over prevalence while 03 sits at 0.7x, and without an esker
        # gate to play the role it plays on the kantarelli map, this is the
        # factor that keeps "Erinomainen" a short list worth walking to.
        "development": 0.72,
        "species": 0.7,     # spruce-dominated
        "mixture": 0.45,
        "light": 0.75,      # roughly 300-1200 stems/ha
        "soil": 0.75,       # mineral or stony ground in a natural drainage state
    },
)


PROFILES = {p.slug: p for p in (KANTARELLI, SUPPILOVAHVERO)}
