-- The words: how a recipe's phrasing reaches the household's own names, and
-- how one unit becomes another.
--
-- Nothing Spoonacular authored is kept here, and an alias is the table that
-- had to be argued about, because the obvious design stores the recipe's
-- phrase as the key. That phrase is the service's text and the line in
-- docs/db.md does not bend for convenience, so the key is a digest of the
-- normalised wording instead. A digest answers the only question a join
-- asks - have we been told what this means before - and cannot be read back
-- as a recipe's words. What is stored in the clear is the household's own
-- name for the thing, which is the household's to keep.

-- The household's own mapping, one row per wording it has met. The key is
-- `matching.ingredients.alias_key`: the wording lowercased, stripped of
-- quantities and preparation, then digested. `confirmed` is the column that
-- earns the table - the match is fuzzy and will be wrong often enough that a
-- silent wrong answer is worse than an asked question, so a row written by
-- the matcher is a guess until a person says otherwise, and only a confirmed
-- row is subtracted from the pantry without asking.
create table ingredient_alias (
    wording_key  text primary key,
    ingredient   text not null,
    confirmed    boolean not null default false,
    confidence   numeric check (confidence >= 0 and confidence <= 1),
    method       text not null default 'fuzzy'
                 check (method in ('exact', 'fuzzy', 'manual')),
    times_seen   integer not null default 1,
    created_at   timestamptz not null default now(),
    confirmed_at timestamptz,
    constraint confirmed_says_when check (
        confirmed = (confirmed_at is not null))
);

create index ingredient_alias_by_ingredient on ingredient_alias (ingredient);

-- What a unit is worth in another unit. Definitions - a kilogram is a
-- thousand grams - stay in code where they are tested and cannot drift; this
-- table carries what only the household or the ingredient can say. A null
-- `ingredient` is a conversion true for anything, so the rule can be general
-- where it may be and specific where it must be: a cup of flour is not a cup
-- of water, and a clove is only a weight once it is a clove of garlic.
-- Volume to mass never happens without a row here - see matching/units.py
-- for why a guess is worse than a refusal.
create table unit_conversion (
    id          integer primary key generated always as identity,
    ingredient  text,
    from_unit   text not null,
    to_unit     text not null,
    factor      numeric not null check (factor > 0),
    source      text not null default 'user'
                check (source in ('user', 'default', 'measured')),
    note        text,
    updated_at  timestamptz not null default now(),
    constraint a_conversion_goes_somewhere check (from_unit <> to_unit)
);

-- One factor per ingredient and pair, and the household's general rules sit
-- under the same constraint: a second row for the same pair is a correction,
-- not another opinion.
create unique index unit_conversion_one_per_pair on unit_conversion
    (coalesce(ingredient, ''), from_unit, to_unit);
