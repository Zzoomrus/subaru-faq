import { QuartzTransformerPlugin } from '@quartz-community/types';

interface Options {
    prefixes: string[];
}
declare const UnlistSources: QuartzTransformerPlugin<Partial<Options>>;

export { UnlistSources };
