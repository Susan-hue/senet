import { Spinner } from "./Spinner";
import styles from "./FullPageLoader.module.css";

export function FullPageLoader() {
  return (
    <div className={styles.wrap}>
      <Spinner size={26} label="Loading" />
    </div>
  );
}
