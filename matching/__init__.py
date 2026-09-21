"""The join between a recipe's words and the pantry's words.

A recipe says "2 cups diced tomatoes" and the cupboard says "tomatoes,
tinned". Two things differ - the wording and the unit - and both have to be
settled before anything can be subtracted. `units` settles the unit on
arithmetic alone; `ingredients` settles the wording, and asks rather than
guesses when it cannot.
"""
