import { Suspense } from 'react';
import ModelPageV2 from './ModelPageV2';

export default function Page() {
  return (
    <Suspense>
      <ModelPageV2 />
    </Suspense>
  );
}
