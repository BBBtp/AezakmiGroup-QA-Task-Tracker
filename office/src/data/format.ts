const pluralRules = new Intl.PluralRules('ru-RU')

export function countLabel(count: number, one: string, few: string, many: string): string {
  const category = pluralRules.select(count)
  return category === 'one' ? one : category === 'few' ? few : many
}
